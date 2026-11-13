import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react';

interface ModalDialogProps {
  title: string;
  onClose: () => void;
  /** While a request is in flight the dialog cannot be dismissed with Escape. */
  busy?: boolean;
  children: ReactNode;
  testId?: string;
}

const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

/**
 * Accessible modal (FE-ADM-07/08/13: never `window.confirm`). It has a name, focuses its first control
 * on open, keeps Tab inside, closes on Escape and gives focus back to the control that opened it.
 */
export function ModalDialog({ title, onClose, busy = false, children, testId }: ModalDialogProps) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = panel.current?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel.current)?.focus();
    return () => opener?.focus();
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape' && !busy) {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = [...(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    const firstItem = items[0];
    const lastItem = items.at(-1);
    if (!firstItem || !lastItem) return;
    if (event.shiftKey && document.activeElement === firstItem) {
      event.preventDefault();
      lastItem.focus();
    } else if (!event.shiftKey && document.activeElement === lastItem) {
      event.preventDefault();
      firstItem.focus();
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-foreground/40 p-4">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        data-testid={testId}
        onKeyDown={onKeyDown}
        className="flex max-h-full w-full max-w-md flex-col gap-4 overflow-y-auto rounded-lg border border-border bg-card p-6 shadow-lg"
      >
        <h2 id={titleId} className="text-lg font-semibold">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}
