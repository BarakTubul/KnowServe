import { beforeEach, describe, expect, it, vi } from 'vitest';

const initializeAuth = vi.fn(() => ({ marker: 'auth' }));
const connectAuthEmulator = vi.fn();
const persistence = { type: 'SESSION' };

vi.mock('firebase/app', () => ({
  getApps: () => [],
  getApp: vi.fn(),
  initializeApp: vi.fn(() => ({ name: 'app' })),
}));
vi.mock('firebase/auth', () => ({
  initializeAuth: (...args: unknown[]) => (initializeAuth as (...a: unknown[]) => unknown)(...args),
  connectAuthEmulator: (...args: unknown[]) => connectAuthEmulator(...args),
  browserSessionPersistence: persistence,
  browserPopupRedirectResolver: { type: 'popup' },
}));

beforeEach(() => {
  vi.resetModules();
  initializeAuth.mockClear();
  connectAuthEmulator.mockClear();
  vi.unstubAllEnvs();
});

describe('FE-AUTH-06 Firebase persistence', () => {
  it('fe_auth_06_firebase_uses_tab_scoped_session_persistence', async () => {
    const { getFirebaseAuth } = await import('./firebase');
    getFirebaseAuth();
    expect(initializeAuth).toHaveBeenCalledTimes(1);
    const options = (initializeAuth.mock.calls[0] as unknown[])[1] as { persistence: unknown };
    expect(options.persistence).toBe(persistence);
  });

  it('fe_auth_06_the_auth_instance_is_created_once', async () => {
    const { getFirebaseAuth } = await import('./firebase');
    expect(getFirebaseAuth()).toBe(getFirebaseAuth());
    expect(initializeAuth).toHaveBeenCalledTimes(1);
  });

  it('fe_auth_06_connects_to_the_emulator_only_when_the_url_is_configured', async () => {
    vi.stubEnv('VITE_FIREBASE_AUTH_EMULATOR_URL', 'http://localhost:9099');
    const { getFirebaseAuth } = await import('./firebase');
    getFirebaseAuth();
    expect(connectAuthEmulator).toHaveBeenCalledWith(
      expect.anything(),
      'http://localhost:9099',
      expect.anything(),
    );
  });

  it('fe_auth_06_no_emulator_connection_without_the_url', async () => {
    vi.stubEnv('VITE_FIREBASE_AUTH_EMULATOR_URL', '');
    const { getFirebaseAuth } = await import('./firebase');
    getFirebaseAuth();
    expect(connectAuthEmulator).not.toHaveBeenCalled();
  });
});
