import { describe, expect, it } from 'vitest';
import { toAuthFlowError } from './firebase-gateway';

const fb = (code: string, customData?: { email: string }) =>
  Object.assign(new Error(code), { code, customData });

describe('Firebase error mapping (FE-AUTH-02, 03, 07, 12, 13)', () => {
  it.each([
    ['auth/invalid-credential', 'invalid-credential'],
    ['auth/wrong-password', 'invalid-credential'],
    ['auth/user-not-found', 'invalid-credential'],
    ['auth/email-already-in-use', 'email-in-use'],
    ['auth/weak-password', 'weak-password'],
    ['auth/credential-already-in-use', 'credential-in-use'],
    ['auth/popup-closed-by-user', 'popup-cancelled'],
    ['auth/popup-blocked', 'popup-blocked'],
    ['auth/expired-action-code', 'expired-code'],
    ['auth/invalid-action-code', 'invalid-code'],
    ['auth/too-many-requests', 'too-many-requests'],
    ['auth/network-request-failed', 'network'],
    ['auth/something-else', 'unknown'],
  ])('fe_auth_02_%s_maps_to_%s', (code, kind) => {
    expect(toAuthFlowError(fb(code)).kind).toBe(kind);
  });

  it('fe_auth_12_account_exists_keeps_the_email_for_the_linking_prompt', () => {
    const mapped = toAuthFlowError(
      fb('auth/account-exists-with-different-credential', { email: 'ada@example.com' }),
    );
    expect(mapped.kind).toBe('account-exists');
    expect(mapped.email).toBe('ada@example.com');
  });

  it('fe_auth_02_non_firebase_errors_become_unknown', () => {
    expect(toAuthFlowError(new TypeError('boom')).kind).toBe('unknown');
    expect(toAuthFlowError('x').kind).toBe('unknown');
  });
});
