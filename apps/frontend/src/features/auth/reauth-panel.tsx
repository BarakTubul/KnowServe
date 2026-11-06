import { useState, type FormEvent } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from './auth-context';
import { describeFlowError } from './messages';

interface ReauthPanelProps {
  /** Runs after the credential was confirmed; the one explicit retry of the session exchange. */
  onConfirmed: () => Promise<void>;
  onCancel?: () => void;
}

/** "Confirm it is you" (FE-AUTH-02, AUTH-30): shown on 401 `REAUTH_REQUIRED`, never retried silently. */
export function ReauthPanel({ onConfirmed, onCancel }: ReauthPanelProps) {
  const { gateway } = useAuth();
  const user = gateway.currentUser();
  const usesPassword = user?.providerIds.includes('password') ?? false;
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(confirm: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await confirm();
      await onConfirmed();
    } catch (e) {
      setError(describeFlowError(e));
    } finally {
      setBusy(false);
    }
  }

  function submitPassword(event: FormEvent) {
    event.preventDefault();
    void run(() => gateway.reauthenticateWithPassword(password));
  }

  return (
    <section data-testid="reauth-panel" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">Confirm it is you</h2>
        <p className="text-sm text-muted-foreground">
          Your last sign-in is too old to start a session. Confirm your credential once more to
          continue{user?.email ? ` as ${user.email}` : ''}.
        </p>
      </div>
      {usesPassword ? (
        <form onSubmit={submitPassword} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="reauth-password">Password</Label>
            <Input
              id="reauth-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={busy}>
            Confirm
          </Button>
        </form>
      ) : (
        <Button disabled={busy} onClick={() => void run(() => gateway.reauthenticateWithGoogle())}>
          Confirm with Google
        </Button>
      )}
      {error && <Alert variant="error">{error}</Alert>}
      {onCancel && (
        <Button variant="outline" size="sm" className="self-start" onClick={onCancel}>
          Cancel
        </Button>
      )}
    </section>
  );
}
