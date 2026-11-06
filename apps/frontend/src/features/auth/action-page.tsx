import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError } from '@/lib/api/errors';
import { useAuth } from './auth-context';
import { ForgotPasswordForm } from './forgot-password-form';
import { AuthFlowError, type AuthGateway } from './gateway-types';
import { describeFlowError, isPasswordLongEnough, MIN_PASSWORD_LENGTH } from './messages';
import { ReauthPanel } from './reauth-panel';

/** Sign-ins older than this ask for the credential again (mirrors the API's freshness window, FE-AUTH-02). */
const REAUTH_AFTER_MS = 5 * 60 * 1000;

type Outcome =
  | { name: 'loading' }
  | { name: 'verified' }
  | { name: 'reset-form'; email: string }
  | { name: 'reset-done' }
  | { name: 'expired' }
  | { name: 'invalid' };

function failure(error: unknown): Outcome {
  return error instanceof AuthFlowError && error.kind === 'expired-code'
    ? { name: 'expired' }
    : { name: 'invalid' };
}

async function resolveCode(gateway: AuthGateway, mode: string, code: string): Promise<Outcome> {
  try {
    await gateway.ready(); // the tab's own Firebase user must be restored before we look at it
    if (mode === 'verifyEmail') {
      await gateway.applyVerificationCode(code);
      return { name: 'verified' };
    }
    if (mode === 'resetPassword') {
      return { name: 'reset-form', email: await gateway.verifyResetCode(code) };
    }
  } catch (error) {
    return failure(error);
  }
  return { name: 'invalid' };
}

/**
 * KnowServe action page for Firebase email links (FE-AUTH-07, FE-AUTH-11): `?mode=verifyEmail` and
 * `?mode=resetPassword`, each with success, expired and invalid states. It never starts a session by
 * itself: after verifying, the user continues explicitly (reauthenticating if the sign-in is stale) or logs in.
 */
export function ActionPage() {
  const { gateway } = useAuth();
  const [params] = useSearchParams();
  const mode = params.get('mode') ?? '';
  const code = params.get('oobCode') ?? '';
  const [outcome, setOutcome] = useState<Outcome>({ name: 'loading' });
  // An action code works once: keep one promise per code so a re-mount cannot spend it twice.
  const pending = useRef<{ key: string; promise: Promise<Outcome> } | null>(null);

  useEffect(() => {
    const key = `${mode}:${code}`;
    if (pending.current?.key !== key) {
      pending.current = { key, promise: resolveCode(gateway, mode, code) };
    }
    let cancelled = false;
    void pending.current.promise.then((result) => {
      if (!cancelled) setOutcome(result);
    });
    return () => {
      cancelled = true;
    };
  }, [gateway, mode, code]);

  return (
    <main data-testid="action-page" className="mx-auto flex max-w-md flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">KnowServe</h1>
      <Card>
        <CardContent className="pt-6">
          {outcome.name === 'loading' && (
            <p role="status" data-testid="action-loading">
              Checking your link...
            </p>
          )}
          {outcome.name === 'verified' && <VerifiedState />}
          {outcome.name === 'reset-form' && (
            <ResetForm
              email={outcome.email}
              code={code}
              onDone={() => setOutcome({ name: 'reset-done' })}
              onFailed={setOutcome}
            />
          )}
          {outcome.name === 'reset-done' && (
            <section data-testid="action-reset-done" className="flex flex-col gap-3">
              <h2 className="text-lg font-semibold">Password changed</h2>
              <p className="text-sm text-muted-foreground">
                Sign in with your new password to continue.
              </p>
              <Link to="/login" className="underline">
                Go to sign in
              </Link>
            </section>
          )}
          {outcome.name === 'expired' && <Dead kind="expired" mode={mode} />}
          {outcome.name === 'invalid' && <Dead kind="invalid" mode={mode} />}
        </CardContent>
      </Card>
    </main>
  );
}

function VerifiedState() {
  const { gateway, status, establishSession } = useAuth();
  const navigate = useNavigate();
  const [reauth, setReauth] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [openedAt] = useState(() => Date.now());
  const user = gateway.currentUser();
  const canContinue = status !== 'authenticated' && user !== null && !user.isAnonymous;
  const stale =
    canContinue && user.lastSignInMs !== null && openedAt - user.lastSignInMs > REAUTH_AFTER_MS;

  async function continueToApp() {
    setBusy(true);
    setError(null);
    try {
      await gateway.reloadUser();
      await establishSession('session', { forceRefresh: true });
      void navigate('/dashboard', { replace: true });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'REAUTH_REQUIRED') setReauth(true);
      else setError(describeFlowError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section data-testid="action-verified" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">Email verified</h2>
        <p className="text-sm text-muted-foreground">
          Your email address is verified. This did not sign you in.
        </p>
      </div>
      {status === 'authenticated' && (
        <Link to="/dashboard" className="underline">
          Back to KnowServe
        </Link>
      )}
      {canContinue && (reauth || stale) && (
        <ReauthPanel
          onConfirmed={async () => {
            await gateway.reloadUser();
            await establishSession('session', { forceRefresh: true });
            void navigate('/dashboard', { replace: true });
          }}
        />
      )}
      {canContinue && !reauth && !stale && (
        <Button className="self-start" disabled={busy} onClick={() => void continueToApp()}>
          Continue to KnowServe
        </Button>
      )}
      {!canContinue && status !== 'authenticated' && (
        <Link to="/login" className="underline">
          Go to sign in
        </Link>
      )}
      {error && <Alert variant="error">{error}</Alert>}
    </section>
  );
}

function ResetForm(props: {
  email: string;
  code: string;
  onDone: () => void;
  onFailed: (outcome: Outcome) => void;
}) {
  const { gateway } = useAuth();
  const [password, setPassword] = useState('');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!isPasswordLongEnough(password)) {
      setFieldError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setFieldError(null);
    setBusy(true);
    try {
      await gateway.confirmPasswordReset(props.code, password);
      props.onDone();
    } catch (e) {
      if (e instanceof AuthFlowError && (e.kind === 'expired-code' || e.kind === 'invalid-code')) {
        props.onFailed(failure(e));
      } else {
        setError(describeFlowError(e));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => void submit(e)}
      data-testid="action-reset-form"
      className="flex flex-col gap-3"
    >
      <h2 className="text-lg font-semibold">Choose a new password</h2>
      <p className="text-sm text-muted-foreground">For {props.email}.</p>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="new-password">New password</Label>
        <Input
          id="new-password"
          type="password"
          autoComplete="new-password"
          required
          aria-invalid={fieldError !== null}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">At least {MIN_PASSWORD_LENGTH} characters.</p>
        {fieldError && (
          <p role="alert" data-testid="password-error" className="text-xs text-destructive">
            {fieldError}
          </p>
        )}
      </div>
      {error && <Alert variant="error">{error}</Alert>}
      <Button type="submit" disabled={busy} className="self-start">
        Change password
      </Button>
    </form>
  );
}

function Dead({ kind, mode }: { kind: 'expired' | 'invalid'; mode: string }) {
  const [requesting, setRequesting] = useState(false);
  const isReset = mode === 'resetPassword';
  const title =
    kind === 'expired'
      ? isReset
        ? 'This reset link has expired'
        : 'This verification link has expired'
      : isReset
        ? 'This reset link is not valid'
        : 'This verification link is not valid';
  return (
    <section data-testid={`action-${kind}`} className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="text-sm text-muted-foreground">
        {kind === 'expired' ? 'Links work for a limited time.' : 'It may have been used already.'}
      </p>
      {isReset ? (
        requesting ? (
          <ForgotPasswordForm onBack={() => setRequesting(false)} />
        ) : (
          <Button className="self-start" onClick={() => setRequesting(true)}>
            Request a new reset link
          </Button>
        )
      ) : (
        <p className="text-sm">
          <Link to="/login" className="underline">
            Sign in
          </Link>{' '}
          to get a new verification email.
        </p>
      )}
    </section>
  );
}
