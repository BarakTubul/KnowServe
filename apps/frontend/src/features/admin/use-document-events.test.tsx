import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeAdminDocument } from '@/test/fake-api';
import { FakeEventSource, stubEventSource } from '@/test/fake-event-source';
import { useDocumentEvents } from './use-document-events';

const DOC = makeAdminDocument({ status: 'queued', can_retry: false });
const STATUS = {
  document_id: DOC.document_id,
  revision_id: DOC.revision_id,
  status: 'processing',
  phase: 'embedding',
  failure_code: null,
  failure_message: null,
  delivery_state: 'processing',
  can_retry: false,
  can_replace: false,
};

function setup(enabled = true) {
  const onStatus = vi.fn();
  const onTerminal = vi.fn();
  const onPoll = vi.fn();
  const view = renderHook(
    (props: { enabled: boolean }) =>
      useDocumentEvents({
        documentId: DOC.document_id,
        enabled: props.enabled,
        onStatus,
        onTerminal,
        onPoll,
        reconnectDelaysMs: [100, 200],
        pollIntervalMs: 1_000,
      }),
    { initialProps: { enabled } },
  );
  return { ...view, onStatus, onTerminal, onPoll };
}

describe('FE-ADM-05/06 status stream hook', () => {
  let fetchSpy: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    stubEventSource();
    // Connecting must never call the API with a mutation: any fetch fails the test below.
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('fe_adm_05_opens_one_stream_for_the_document_with_credentials_and_reports_status_events', () => {
    const { result, onStatus } = setup();
    expect(FakeEventSource.instances).toHaveLength(1);
    const source = FakeEventSource.instances[0]!;
    expect(source.url).toBe(`/api/v1/admin/documents/${DOC.document_id}/events`);
    expect(source.withCredentials).toBe(true);
    expect(result.current).toBe('connecting');

    act(() => source.emit('status', STATUS));
    expect(onStatus).toHaveBeenCalledWith(STATUS);
    expect(result.current).toBe('live');
  });

  it('fe_adm_06_end_terminal_closes_the_stream_and_does_not_reconnect', () => {
    const { result, onTerminal } = setup();
    const source = FakeEventSource.instances[0]!;
    act(() => source.emit('status', { ...STATUS, status: 'ready', phase: null }));
    act(() => source.emit('end', { reason: 'terminal' }));
    expect(source.closed).toBe(true);
    expect(onTerminal).toHaveBeenCalledTimes(1);
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(result.current).toBe('closed');
  });

  it('fe_adm_06_end_timeout_reconnects_with_a_new_stream_and_creates_no_job', () => {
    const { result, onTerminal } = setup();
    const first = FakeEventSource.instances[0]!;
    act(() => first.emit('status', STATUS));
    act(() => first.emit('end', { reason: 'timeout' }));
    expect(first.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.open).toHaveLength(1);
    expect(onTerminal).not.toHaveBeenCalled();
    // The new stream starts from a fresh status; the hook sends nothing but the GET stream.
    act(() => FakeEventSource.instances[1]!.emit('status', STATUS));
    expect(result.current).toBe('live');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('fe_adm_06_a_dropped_stream_reconnects_after_a_delay_then_falls_back_to_polling', () => {
    vi.useFakeTimers();
    const { result, onPoll } = setup();
    act(() => FakeEventSource.instances[0]!.fail());
    expect(result.current).toBe('connecting');
    expect(FakeEventSource.instances).toHaveLength(1);

    act(() => void vi.advanceTimersByTime(100));
    expect(FakeEventSource.instances).toHaveLength(2);
    act(() => FakeEventSource.instances[1]!.fail());
    act(() => void vi.advanceTimersByTime(200));
    expect(FakeEventSource.instances).toHaveLength(3);

    // The reconnect delays are used up: the list becomes the source of truth.
    act(() => FakeEventSource.instances[2]!.fail());
    expect(result.current).toBe('degraded');
    expect(onPoll).toHaveBeenCalledTimes(1);
    act(() => void vi.advanceTimersByTime(2_000));
    expect(onPoll).toHaveBeenCalledTimes(3);
    expect(FakeEventSource.open).toHaveLength(0);
  });

  it('fe_adm_06_a_status_event_resets_the_failure_count', () => {
    vi.useFakeTimers();
    const { result } = setup();
    act(() => FakeEventSource.instances[0]!.fail());
    act(() => void vi.advanceTimersByTime(100));
    act(() => FakeEventSource.instances[1]!.emit('status', STATUS));
    expect(result.current).toBe('live');
    act(() => FakeEventSource.instances[1]!.fail());
    act(() => void vi.advanceTimersByTime(100)); // the first delay again, not the second
    expect(FakeEventSource.instances).toHaveLength(3);
  });

  it('opens_no_stream_for_a_document_that_cannot_change_and_closes_on_unmount', () => {
    const idle = setup(false);
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(idle.result.current).toBe('closed');
    idle.unmount();

    const live = setup(true);
    const source = FakeEventSource.instances[0]!;
    live.unmount();
    expect(source.closed).toBe(true);
  });

  it('starts_and_stops_with_the_enabled_flag', () => {
    const view = setup(false);
    view.rerender({ enabled: true });
    expect(FakeEventSource.open).toHaveLength(1);
    view.rerender({ enabled: false });
    expect(FakeEventSource.open).toHaveLength(0);
  });

  it('ignores_malformed_events_without_failing', () => {
    const { onStatus, result } = setup();
    const source = FakeEventSource.instances[0]!;
    act(() => source.emit('status', 'not json'));
    act(() => source.emit('status', { unexpected: true }));
    expect(onStatus).not.toHaveBeenCalled();
    expect(result.current).toBe('connecting');
  });

  it('falls_back_to_polling_when_the_browser_has_no_event_source', () => {
    vi.useFakeTimers();
    vi.stubGlobal('EventSource', undefined);
    const { result, onPoll } = setup();
    act(() => void vi.advanceTimersByTime(0));
    // The failure is handled like a dropped stream: delays first, then polling.
    act(() => void vi.advanceTimersByTime(1_000));
    expect(result.current).toBe('degraded');
    expect(onPoll).toHaveBeenCalled();
  });
});
