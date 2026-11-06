import { useState, type FormEvent } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { DemoModeIndicator } from '@/features/dashboard/demo-mode-indicator';
import { ApiError } from '@/lib/api/errors';
import { useAuth } from './auth-context';
import { ForgotPasswordForm } from './forgot-password-form';
import { AuthFlowError } from './gateway-types';
import { LinkAccountPanel } from './link-account-panel';
import { describeFlowError } from './messages';
import { ReauthPanel } from './reauth-panel';
import { SignupForm } from './signup-form';
import { VerifyEmailPanel } from './verify-email-panel';

type View =
  | { name: 'login' }
  | { name: 'signup' }
  | { name: 'forgot' }
  | { name: 'verify'; email: string; reason: 'signup' | 'login' }
  | { name: 'link'; email: string }
  | { name: 'reauth' };

/** The single login screen (FE-AUTH-02): password, Google, forgot password, sign up and Try Demo. */
export function LoginPage() {
  const { gateway, establishSession, startDemo, sessionNotice } = useAuth();
  const [view, setView] = useState<View>({ name: 'login' });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const toLogin = () => {
    gateway.cancelPendingLink();
    setError(null);
    setView({ name: 'login' });
  };

  /** One session exchange. The two documented 4xx outcomes lead to their own state, not an error. */
  async function exchange(forceRefresh = false): Promise<void> {
    try {
      await establishSession('session', { forceRefresh });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'EMAIL_NOT_VERIFIED') {
        setView({ name: 'verify', email: gateway.currentUser()?.email ?? email, reason: 'login' });
        return;
      }
      if (e instanceof ApiError && e.code === 'REAUTH_REQUIRED') {
        setView({ name: 'reauth' });
        return;
      }
      throw e;
    }
  }

  async function guarded(run: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await run();
    } catch (e) {
      if (e instanceof AuthFlowError && e.kind === 'account-exists' && e.email) {
        setView({ name: 'link', email: e.email });
      } else {
        setError(describeFlowError(e));
      }
    } finally {
      setBusy(false);
    }
  }

  function submitPassword(event: FormEvent) {
    event.preventDefault();
    void guarded(async () => {
      await gateway.signInWithPassword(email.trim(), password);
      await exchange();
    });
  }

  const googleSignIn = () =>
    guarded(async () => {
      await gateway.signInWithGoogle();
      await exchange();
    });

  const tryDemo = () =>
    guarded(async () => {
      await startDemo();
    });

  return (
    <main data-testid="login-page" className="mx-auto flex max-w-md flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">KnowServe</h1>
        <DemoModeIndicator />
      </header>
      <Card>
        <CardContent className="pt-6">
          {view.name === 'login' && (
            <div className="flex flex-col gap-5">
              <CardHeader className="p-0">
                <CardTitle>Sign in</CardTitle>
              </CardHeader>
              {sessionNotice && <Alert variant="info">{sessionNotice}</Alert>}
              <form onSubmit={submitPassword} className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="login-email">Email</Label>
                  <Input
                    id="login-email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="login-password">Password</Label>
                  <Input
                    id="login-password"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
                <Button type="submit" disabled={busy}>
                  Sign in
                </Button>
                <button
                  type="button"
                  className="self-start text-sm underline"
                  onClick={() => setView({ name: 'forgot' })}
                >
                  Forgot password?
                </button>
              </form>
              <Button variant="outline" disabled={busy} onClick={() => void googleSignIn()}>
                Continue with Google
              </Button>
              {error && <Alert variant="error">{error}</Alert>}
              <div className="flex flex-col gap-2 border-t border-border pt-4">
                <Button variant="secondary" disabled={busy} onClick={() => void tryDemo()}>
                  Try Demo
                </Button>
                <p className="text-xs text-muted-foreground">
                  Try Demo needs no sign-up. The documents and organization are fictional.
                </p>
                <p className="text-sm">
                  New here?{' '}
                  <button
                    type="button"
                    className="underline"
                    onClick={() => {
                      setError(null);
                      setView({ name: 'signup' });
                    }}
                  >
                    Sign up
                  </button>
                </p>
              </div>
            </div>
          )}
          {view.name === 'signup' && (
            <SignupForm
              onCreated={(created) => setView({ name: 'verify', email: created, reason: 'signup' })}
              onBack={toLogin}
            />
          )}
          {view.name === 'forgot' && <ForgotPasswordForm onBack={toLogin} />}
          {view.name === 'verify' && (
            <VerifyEmailPanel
              email={view.email}
              reason={view.reason}
              onContinue={() => exchange(true)}
              onBack={toLogin}
            />
          )}
          {view.name === 'link' && (
            <LinkAccountPanel
              email={view.email}
              onLinked={() => exchange(true)}
              onCancel={toLogin}
            />
          )}
          {view.name === 'reauth' && (
            <ReauthPanel
              onConfirmed={async () => {
                // The single, explicit retry after the user confirmed the credential.
                await establishSession('session', { forceRefresh: true });
              }}
              onCancel={toLogin}
            />
          )}
        </CardContent>
      </Card>
    </main>
  );
}
