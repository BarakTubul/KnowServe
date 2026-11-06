import { useEffect, useState, type FormEvent } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '@/features/auth/auth-context';
import { AuthFlowError } from '@/features/auth/gateway-types';
import {
  describeFlowError,
  isPasswordLongEnough,
  MIN_PASSWORD_LENGTH,
} from '@/features/auth/messages';
import { ReauthPanel } from '@/features/auth/reauth-panel';
import { ApiError } from '@/lib/api/errors';

type Step =
  | { name: 'form' }
  | { name: 'pending'; email: string }
  | { name: 'reauth'; email: string | null }
  | { name: 'collision' };

const COLLISION_KINDS = new Set(['email-in-use', 'credential-in-use', 'account-exists']);

/**
 * Create an account from a Demo (FE-AUTH-13, AUTH-34): link a credential to the anonymous Firebase user,
 * then convert. A password signup stays in Demo (pending) until the email is verified.
 */
export function CreateAccountPanel({ onConverted }: { onConverted: () => void }) {
  const { gateway, establishSession, logout } = useAuth();
  const [step, setStep] = useState<Step>({ name: 'form' });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The pending state lives in Firebase (tab-scoped), so it survives a reload: a linked non-anonymous user
  // (verified or not) while the KnowServe session is still a Demo: the conversion is not finished.
  useEffect(() => {
    let cancelled = false;
    void gateway.ready().then(() => {
      const user = gateway.currentUser();
      if (!cancelled && user && !user.isAnonymous && user.email) {
        setStep({ name: 'pending', email: user.email });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [gateway]);

  /** Fresh token, then the conversion call. A stale sign-in gets the explicit confirm step. */
  async function convert(): Promise<void> {
    try {
      await establishSession('convert', { forceRefresh: true });
      onConverted();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'REAUTH_REQUIRED') {
        setStep({ name: 'reauth', email: gateway.currentUser()?.email ?? null });
        return;
      }
      throw e;
    }
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
    } catch (e) {
      if (e instanceof AuthFlowError && COLLISION_KINDS.has(e.kind)) setStep({ name: 'collision' });
      else setError(describeFlowError(e));
    } finally {
      setBusy(false);
    }
  }

  function submitPassword(event: FormEvent) {
    event.preventDefault();
    if (!isPasswordLongEnough(password)) {
      setFieldError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    setFieldError(null);
    void run(async () => {
      await gateway.linkEmailPassword(email.trim(), password);
      setStep({ name: 'pending', email: email.trim() });
    });
  }

  const linkGoogle = () =>
    run(async () => {
      const user = await gateway.linkGoogle();
      // Google accounts arrive verified: convert at once.
      if (user.emailVerified) await convert();
      else setStep({ name: 'pending', email: user.email ?? '' });
    });

  const checkVerified = () =>
    run(async () => {
      const user = await gateway.reloadUser();
      if (!user?.emailVerified) {
        setMessage('Your email is not verified yet. Open the link in the email, then try again.');
        return;
      }
      await convert();
    });

  const resend = () =>
    run(async () => {
      await gateway.resendVerification();
      setMessage('We sent the verification email again.');
    });

  async function signInInstead() {
    await logout({ toLogin: true });
  }

  return (
    <Card data-testid="create-account">
      <CardHeader>
        <CardTitle>Create an account</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {step.name === 'form' && (
          <>
            <p className="text-sm text-muted-foreground">
              Keep what you did in this Demo: your history and departments move into your new
              account.
            </p>
            <form onSubmit={submitPassword} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="convert-email">Email</Label>
                <Input
                  id="convert-email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="convert-password">Password</Label>
                <Input
                  id="convert-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  aria-invalid={fieldError !== null}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  At least {MIN_PASSWORD_LENGTH} characters.
                </p>
                {fieldError && (
                  <p role="alert" data-testid="password-error" className="text-xs text-destructive">
                    {fieldError}
                  </p>
                )}
              </div>
              <Button type="submit" disabled={busy} className="self-start">
                Create account with email
              </Button>
            </form>
            <Button
              variant="outline"
              disabled={busy}
              className="self-start"
              onClick={() => void linkGoogle()}
            >
              Continue with Google
            </Button>
          </>
        )}
        {step.name === 'pending' && (
          <div data-testid="convert-pending" className="flex flex-col gap-3">
            <p className="text-sm">
              Check your email{step.email ? ` (${step.email})` : ''} and open the verification link.
              You stay in Demo, with your history, until the address is verified.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button disabled={busy} onClick={() => void checkVerified()}>
                I have verified my email
              </Button>
              <Button variant="outline" disabled={busy} onClick={() => void resend()}>
                Resend verification email
              </Button>
            </div>
          </div>
        )}
        {step.name === 'reauth' && (
          <ReauthPanel
            onConfirmed={async () => {
              await establishSession('convert', { forceRefresh: true });
              onConverted();
            }}
            onCancel={() => setStep({ name: 'pending', email: step.email ?? '' })}
          />
        )}
        {step.name === 'collision' && (
          <div data-testid="convert-collision" className="flex flex-col gap-3">
            <Alert variant="info">
              This email or Google account already has a KnowServe account. Your Demo history will
              not be moved into that account, and nothing is merged.
            </Alert>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => void signInInstead()}>Sign in to that account instead</Button>
              <Button variant="outline" onClick={() => setStep({ name: 'form' })}>
                Keep using Demo
              </Button>
            </div>
          </div>
        )}
        {message && <Alert variant="info">{message}</Alert>}
        {error && <Alert variant="error">{error}</Alert>}
      </CardContent>
    </Card>
  );
}
