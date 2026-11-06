// Helpers for the Firebase Auth Emulator (the only Firebase these specs may talk to).
import { randomUUID } from 'node:crypto';

export const EMULATOR = process.env['E2E_FIREBASE_AUTH_EMULATOR_URL'] ?? 'http://localhost:9099';
export const PROJECT = process.env['E2E_FIREBASE_PROJECT_ID'] ?? 'demo-knowserve';
const API_KEY = 'fake-api-key';
const ADMIN = { Authorization: 'Bearer owner', 'content-type': 'application/json' };

export const PASSWORD = 'correct horse battery';

/** A unique email per test so specs never collide in the shared emulator. */
export function uniqueEmail(prefix = 'user'): string {
  return `${prefix}-${randomUUID().slice(0, 8)}@example.test`;
}

interface OobCode {
  email: string;
  requestType: 'VERIFY_EMAIL' | 'PASSWORD_RESET' | string;
  oobCode: string;
}

/** The newest emulator-sent code of a kind for an email (the emulator "sends" mail into this list). */
export async function latestOobCode(
  email: string,
  requestType: 'VERIFY_EMAIL' | 'PASSWORD_RESET',
): Promise<string> {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const res = await fetch(`${EMULATOR}/emulator/v1/projects/${PROJECT}/oobCodes`);
    const body = (await res.json()) as { oobCodes: OobCode[] };
    const match = body.oobCodes
      .filter((c) => c.email === email && c.requestType === requestType)
      .at(-1);
    if (match) return match.oobCode;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`no ${requestType} code for ${email} in the emulator`);
}

/** The path of the KnowServe action page for a Firebase email link. */
export function actionPath(mode: 'verifyEmail' | 'resetPassword', oobCode: string): string {
  return `/auth/action?mode=${mode}&oobCode=${encodeURIComponent(oobCode)}`;
}

/** Creates an email + password account that is already verified (no mail step). */
export async function createVerifiedUser(email: string, password = PASSWORD): Promise<string> {
  const created = await fetch(
    `${EMULATOR}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=${API_KEY}`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email, password, returnSecureToken: true }),
    },
  );
  const { localId } = (await created.json()) as { localId: string };
  await fetch(`${EMULATOR}/identitytoolkit.googleapis.com/v1/projects/${PROJECT}/accounts:update`, {
    method: 'POST',
    headers: ADMIN,
    body: JSON.stringify({ localId, emailVerified: true }),
  });
  return localId;
}
