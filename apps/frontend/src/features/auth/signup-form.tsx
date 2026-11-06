import { useState, type FormEvent } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from './auth-context';
import { AuthFlowError } from './gateway-types';
import {
  describeFlowError,
  isPasswordLongEnough,
  MIN_PASSWORD_LENGTH,
  SIGN_UP_NEUTRAL_MESSAGE,
} from './messages';

interface SignupFormProps {
  onCreated: (email: string) => void;
  onBack: () => void;
}

/** Email + password signup. Client check: minimum length only; the final policy is Firebase's (FE-AUTH-03). */
export function SignupForm({ onCreated, onBack }: SignupFormProps) {
  const { gateway } = useAuth();
  const [email, setEmail] = useState('');
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
      await gateway.signUpWithPassword(email.trim(), password);
      onCreated(email.trim());
    } catch (e) {
      setError(
        e instanceof AuthFlowError && e.kind === 'email-in-use'
          ? SIGN_UP_NEUTRAL_MESSAGE
          : describeFlowError(e),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Create an account</h2>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="signup-email">Email</Label>
        <Input
          id="signup-email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="signup-password">Password</Label>
        <Input
          id="signup-password"
          type="password"
          autoComplete="new-password"
          required
          aria-invalid={fieldError !== null}
          aria-describedby="signup-password-hint"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <p id="signup-password-hint" className="text-xs text-muted-foreground">
          At least {MIN_PASSWORD_LENGTH} characters. A long passphrase is fine.
        </p>
        {fieldError && (
          <p role="alert" data-testid="password-error" className="text-xs text-destructive">
            {fieldError}
          </p>
        )}
      </div>
      {error && <Alert variant="error">{error}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          Create account
        </Button>
        <Button type="button" variant="outline" onClick={onBack}>
          Back to sign in
        </Button>
      </div>
    </form>
  );
}
