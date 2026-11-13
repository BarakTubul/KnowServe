import { vi } from 'vitest';

type Listener = (event: MessageEvent) => void;

/** A controllable EventSource for tests: `emit` delivers a named event, `fail` simulates a drop. */
export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  readonly withCredentials: boolean;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, listener: Listener) {
    this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);
  }

  close() {
    this.closed = true;
  }

  emit(name: string, data: unknown) {
    const text = typeof data === 'string' ? data : JSON.stringify(data);
    for (const listener of this.listeners.get(name) ?? []) {
      listener({ data: text } as MessageEvent);
    }
  }

  fail() {
    this.onerror?.();
  }

  static get open() {
    return FakeEventSource.instances.filter((source) => !source.closed);
  }
}

/** Installs the fake as the global EventSource; `vi.unstubAllGlobals` (test setup) removes it. */
export function stubEventSource(): typeof FakeEventSource {
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
  return FakeEventSource;
}
