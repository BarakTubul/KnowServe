import type { ApiError } from './errors';

type Listener = (error: ApiError) => void;

const listeners = new Set<Listener>();

/** Subscribe to errors of authenticated API calls (FE-AUTH-05). Returns the unsubscribe function. */
export function subscribeApiErrors(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function emitApiError(error: ApiError): void {
  for (const listener of [...listeners]) listener(error);
}
