import { useState } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { useAuth } from './auth-context';
import { describeFlowError } from './messages';

interface VerifyEmailPanelProps {
  email: string;
  /** `signup` after creating the account, `login` when sign-in found an unverified address. */
  reason: 'signup' | 'login';
  /** Explicit continue once the address is verified: reload, fresh token, session exchange. */
  onContinue: () => Promise<void>;
  onBack: () => void;
}

/** "Check your email" / "Verify your email" state with resend (FE-AUTH-02, FE-AUTH-03). */
export function VerifyEmailPanel({ email, reason, onContinue, onBack }: VerifyEmailPanelProps) {
  const { gateway } = useAuth();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function resend() {
    setBusy(true);
    setError(null);
    try {
      await gateway.resendVerification();
      setMessage('We sent the verification email again.');
    } catch (e) {
      setError(describeFlowError(e));
    } finally {
      setBusy(false);
    }
  }

  async function proceed() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const user = await gateway.reloadUser();
      if (!user?.emailVerified) {
        setMessage('Your email is not verified yet. Open the link in the email, then try again.');
        return;
      }
      await onContinue();
    } catch (e) {
      setError(describeFlowError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section data-testid="verify-email-panel" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">
          {reason === 'signup' ? 'Check your email' : 'Verify your email'}
        </h2>
        <p className="text-sm text-muted-foreground">
          {reason === 'signup'
            ? `We sent a verification link to ${email}.`
            : `The address ${email} is not verified yet. We can send the link again.`}{' '}
          Open it, then come back and continue.
        </p>
      </div>
      {message && <Alert variant="info">{message}</Alert>}
      {error && <Alert variant="error">{error}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={() => void proceed()}>
          I have verified my email
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => void resend()}>
          Resend verification email
        </Button>
        <Button variant="outline" onClick={onBack}>
          Back to sign in
        </Button>
      </div>
    </section>
  );
}
