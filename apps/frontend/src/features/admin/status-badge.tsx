import { cn } from '@/lib/utils';
import type { AdminDocument } from './admin-api';
import { PHASE_LABEL, STATUS_LABEL } from './admin-text';

const TONE: Record<AdminDocument['status'], string> = {
  queued: 'border-border bg-muted text-foreground',
  processing: 'border-border bg-muted text-foreground',
  ready: 'border-success text-success',
  failed: 'border-destructive text-destructive',
};

/**
 * One badge per status (FE-ADM-10). `processing` names its phase, and there are no percentages
 * (ING-07): the phase is all the server knows. The text, not the colour, carries the meaning.
 */
export function StatusBadge({ document }: { document: Pick<AdminDocument, 'status' | 'phase'> }) {
  const phase =
    document.status === 'processing' && document.phase ? PHASE_LABEL[document.phase] : null;
  return (
    <span
      data-testid={`status-badge-${document.status}`}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
        TONE[document.status],
      )}
    >
      {STATUS_LABEL[document.status]}
      {phase && <span className="font-normal">: {phase}</span>}
    </span>
  );
}
