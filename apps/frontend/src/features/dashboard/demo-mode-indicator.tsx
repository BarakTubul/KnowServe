import { useEffect, useState } from 'react';
import { useAuth } from '@/features/auth/auth-context';

/** "2 h 5 min left" for a number of milliseconds; "less than a minute" at the end. */
export function formatTimeLeft(ms: number): string {
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return 'less than a minute';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours > 0 ? `${hours} h ${rest} min` : `${rest} min`;
}

/** Always visible on authenticated screens (PROD-01); a Demo session also shows its remaining time. */
export function DemoModeIndicator() {
  const { identity } = useAuth();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const left = identity ? Date.parse(identity.expires_at) - now : null;
  return (
    <div className="flex items-center gap-2">
      <span
        data-testid="demo-mode-badge"
        className="rounded-full bg-secondary px-3 py-1 text-xs font-medium text-secondary-foreground"
      >
        Demo Mode
      </span>
      {identity?.kind === 'demo' && left !== null && (
        <span data-testid="demo-time-left" className="text-xs text-muted-foreground">
          Demo session: {formatTimeLeft(Math.max(left, 0))} left
        </span>
      )}
    </div>
  );
}
