import { useState, type FormEvent } from 'react';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from './auth-context';
import { RESET_CONFIRMATION } from './messages';

/** Reset request: the same confirmation for any email, existing or not (FE-AUTH-11, AUTH-33). */
export function ForgotPasswordForm({ onBack }: { onBack: () => void }) {
  const { gateway } = useAuth();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await gateway.sendPasswordReset(email.trim());
    } catch {
      // Deliberately ignored: an error must not reveal whether the account exists.
    } finally {
      setBusy(false);
      setSent(true);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Reset your password</h2>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="reset-email">Email</Label>
        <Input
          id="reset-email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      {sent && (
        <Alert variant="info" data-testid="reset-confirmation">
          {RESET_CONFIRMATION}
        </Alert>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          Send reset link
        </Button>
        <Button type="button" variant="outline" onClick={onBack}>
          Back to sign in
        </Button>
      </div>
    </form>
  );
}
