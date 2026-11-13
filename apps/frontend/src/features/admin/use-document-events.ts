import { useEffect, useRef, useState } from 'react';
import { openEventStream } from '@/lib/api/sse';
import { documentEventsUrl, type AdminDocument } from './admin-api';

/** What `event: status` carries (`DocumentProcessingStatus`, docs/contracts/admin-api.md). */
export type ProcessingStatus = Pick<
  AdminDocument,
  | 'document_id'
  | 'revision_id'
  | 'status'
  | 'phase'
  | 'failure_code'
  | 'failure_message'
  | 'delivery_state'
  | 'can_retry'
  | 'can_replace'
>;

export type StreamState = 'connecting' | 'live' | 'degraded' | 'closed';

/** Waits before each reconnect after a failure; when they run out the list is polled instead. */
export const RECONNECT_DELAYS_MS = [1_000, 3_000, 10_000] as const;
export const FALLBACK_POLL_MS = 10_000;

interface Options {
  documentId: string;
  /** Only documents that can still change (`queued`, `processing`) need a stream. */
  enabled: boolean;
  onStatus: (status: ProcessingStatus) => void;
  /** `event: end` with reason `terminal`: the document reached `ready` or `failed`. */
  onTerminal: () => void;
  /** The stream could not be kept: refresh the list from the database (the fallback of FE-ADM-06). */
  onPoll: () => void;
  reconnectDelaysMs?: readonly number[];
  pollIntervalMs?: number;
}

function parseJson(data: string): unknown {
  try {
    return JSON.parse(data) as unknown;
  } catch {
    return undefined;
  }
}

function isStatus(value: unknown): value is ProcessingStatus {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as ProcessingStatus).document_id === 'string' &&
    typeof (value as ProcessingStatus).status === 'string'
  );
}

/**
 * Subscribes to `GET /v1/admin/documents/{id}/events` (ING-07, FE-ADM-05/06).
 *
 * - `status` events are passed on as they arrive; the server builds each one from the database.
 * - `end` with reason `terminal` stops the stream; with reason `timeout` (or anything else) the hook
 *   reconnects at once. There are no event ids and no replay: a reconnect starts with a fresh `status`,
 *   and connecting never creates or requeues a job.
 * - A failed connection is retried after growing delays. When those run out the state is `degraded`
 *   and `onPoll` runs on an interval, so the list (the database) stays the source of truth.
 */
export function useDocumentEvents(options: Options): StreamState {
  const { documentId, enabled } = options;
  const [state, setState] = useState<StreamState>(enabled ? 'connecting' : 'closed');
  const callbacks = useRef(options);
  useEffect(() => {
    callbacks.current = options;
  });

  useEffect(() => {
    if (!enabled) return;
    const delays = callbacks.current.reconnectDelaysMs ?? RECONNECT_DELAYS_MS;
    const pollMs = callbacks.current.pollIntervalMs ?? FALLBACK_POLL_MS;
    let stopped = false;
    let failures = 0;
    let stream: { close(): void } | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let pollTimer: ReturnType<typeof setInterval> | undefined;

    const connect = () => {
      if (stopped) return;
      stream = openEventStream(documentEventsUrl(documentId), ['status', 'end'], {
        onEvent(name, data) {
          const payload = parseJson(data);
          if (name === 'status') {
            if (!isStatus(payload)) return;
            failures = 0;
            setState('live');
            callbacks.current.onStatus(payload);
            return;
          }
          const reason = (payload as { reason?: unknown } | undefined)?.reason;
          stream?.close();
          stream = null;
          if (reason === 'terminal') {
            setState('closed');
            callbacks.current.onTerminal();
          } else {
            setState('connecting');
            connect(); // a timeout: the server asks for a fresh stream
          }
        },
        onError() {
          stream = null;
          const delay = delays[failures];
          failures += 1;
          if (delay !== undefined) {
            setState('connecting');
            retryTimer = setTimeout(connect, delay);
            return;
          }
          setState('degraded');
          callbacks.current.onPoll();
          pollTimer = setInterval(() => callbacks.current.onPoll(), pollMs);
        },
      });
    };
    connect();

    return () => {
      stopped = true;
      stream?.close();
      clearTimeout(retryTimer);
      clearInterval(pollTimer);
    };
  }, [documentId, enabled]);

  return enabled ? state : 'closed';
}
