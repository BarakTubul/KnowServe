import { useState, type FormEvent } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from './auth-context';
import { AuthFlowError } from './gateway-types';
import { describeFlowError } from './messages';

interface LinkAccountPanelProps {
  email: string;
  /** Runs once Google is linked to the existing account; the user then gets a session. */
  onLinked: () => Promise<void>;
  onCancel: () => void;
}

/**
 * Google sign-in found a password account for this email (FE-AUTH-12, AUTH-32). The user signs in with
 * the password first; only then is Google linked. Never silent, never for an unverified account.
 */
export function LinkAccountPanel({ email, onLinked, onCancel }: LinkAccountPanelProps) {
  const { gateway } = useAuth();
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await gateway.linkPendingGoogle(email, password);
      await onLinked();
    } catch (e) {
      if (e instanceof AuthFlowError && e.kind === 'unverified') setUnverified(true);
      else setError(describeFlowError(e));
    } finally {
      setBusy(false);
    }
  }

  if (unverified) {
    return (
      <section data-testid="link-unverified" className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">We cannot link this account yet</h2>
        <p className="text-sm text-muted-foreground">
          The email {email} has not been verified, so Google cannot be added to it. Sign in with
          your password and verify your email first.
        </p>
        <Button variant="outline" className="self-start" onClick={onCancel}>
          Back to sign in
        </Button>
      </section>
    );
  }

  return (
    <form
      onSubmit={(e) => void submit(e)}
      data-testid="link-account"
      className="flex flex-col gap-3"
    >
      <h2 className="text-lg font-semibold">An account with this email already exists</h2>
      <p className="text-sm text-muted-foreground">
        {email} already has a password account. Sign in with that password first, and we will add
        Google to the same account.
      </p>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="link-password">Password for {email}</Label>
        <Input
          id="link-password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      {error && <Alert variant="error">{error}</Alert>}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          Sign in and link Google
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
