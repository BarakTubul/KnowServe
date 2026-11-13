import { useCallback, useRef } from 'react';
import { newIdempotencyKey } from '@/lib/api/client';

/**
 * One `Idempotency-Key` per user action (docs/contracts/admin-api.md, ADM-03).
 *
 * `keyFor(fingerprint)` returns the same key while the fingerprint (the file and values being sent) is
 * unchanged, so a retry after a timeout or a double click replays the first request instead of creating a
 * second document. A different request gets a new key, because the server answers 409
 * `IDEMPOTENCY_KEY_REUSED` for one key with different content. `reset()` ends the action after success.
 */
export function useActionKey() {
  const current = useRef<{ key: string; fingerprint: string } | null>(null);
  const keyFor = useCallback((fingerprint: string): string => {
    if (current.current?.fingerprint !== fingerprint) {
      current.current = { key: newIdempotencyKey(), fingerprint };
    }
    return current.current.key;
  }, []);
  const reset = useCallback(() => {
    current.current = null;
  }, []);
  return { keyFor, reset };
}

/** A fingerprint of a File that is cheap and stable for the same selected file. */
export function fileFingerprint(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}
