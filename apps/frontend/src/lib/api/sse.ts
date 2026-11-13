/**
 * Thin wrapper over the browser's EventSource: the SSE helper of the one API client (FE-ARCH-01).
 * It opens a stream with the session cookie, forwards the named events and reports failures. It never
 * reconnects by itself (the caller decides), because a native reconnect would hide a dropped stream.
 * `EventSource` is read at call time so tests can stub it.
 */
export interface EventStreamHandlers {
  onOpen?: () => void;
  onEvent: (name: string, data: string) => void;
  /** The connection failed or was refused (401, 403, 404 or a dropped network). The stream is closed. */
  onError: () => void;
}

export interface EventStream {
  close(): void;
}

export function openEventStream(
  url: string,
  eventNames: readonly string[],
  handlers: EventStreamHandlers,
): EventStream {
  let closed = false;
  if (typeof globalThis.EventSource === 'undefined') {
    // No SSE support: report it like a failed connection so the caller falls back to polling.
    const timer = setTimeout(() => {
      if (!closed) handlers.onError();
    }, 0);
    return {
      close() {
        closed = true;
        clearTimeout(timer);
      },
    };
  }
  const source = new globalThis.EventSource(url, { withCredentials: true });
  source.onopen = () => {
    if (!closed) handlers.onOpen?.();
  };
  for (const name of eventNames) {
    source.addEventListener(name, (event) => {
      if (!closed) handlers.onEvent(name, String((event as MessageEvent).data ?? ''));
    });
  }
  source.onerror = () => {
    if (closed) return;
    closed = true;
    source.close();
    handlers.onError();
  };
  return {
    close() {
      closed = true;
      source.close();
    },
  };
}
