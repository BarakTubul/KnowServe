import { Button } from '@/components/ui/button';
import { useAuth } from './auth-context';

/** Global message for 429 and 503 AI errors (FE-AUTH-05). The user stays signed in. */
export function ApiNoticeBanner() {
  const { notice, dismissNotice } = useAuth();
  if (!notice) return null;
  return (
    <div
      role="status"
      data-testid={`api-notice-${notice.kind}`}
      className="fixed inset-x-0 top-0 z-50 flex items-center justify-between gap-4 border-b border-border bg-muted px-4 py-2 text-sm"
    >
      <p>{notice.message}</p>
      <Button variant="outline" size="sm" onClick={dismissNotice}>
        Dismiss
      </Button>
    </div>
  );
}
