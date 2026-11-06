// A contract-faithful fake of the KnowServe auth API for the auth Playwright specs, installed with
// page.route on /api/v1/**. It follows docs/contracts/auth-session.md: it reads the REAL Firebase
// emulator ID token (unsigned JWT) and applies the contract's rules (provider, email_verified,
// freshness, CSRF, Demo expiry). It is NOT backend evidence: the same specs run against the real API
// with E2E_REAL_API=1, where this fake is not installed.
import { randomUUID } from 'node:crypto';
import type { Page, Route } from '@playwright/test';

export const REAL_API = process.env['E2E_REAL_API'] === '1';

const DEPARTMENTS = [
  { id: '00000000-0000-4000-8000-000000000001', name: 'Human Resources', slug: 'hr' },
  { id: '00000000-0000-4000-8000-000000000002', name: 'Finance', slug: 'finance' },
  { id: '00000000-0000-4000-8000-000000000003', name: 'Engineering', slug: 'engineering' },
  { id: '00000000-0000-4000-8000-000000000004', name: 'Legal', slug: 'legal' },
  { id: '00000000-0000-4000-8000-000000000005', name: 'Operations', slug: 'operations' },
];

interface User {
  id: string;
  uid: string;
  kind: 'demo' | 'registered';
  email: string | null;
  provider: string;
  departmentId: string | null;
  demoExpired: boolean;
}

interface Session {
  userId: string;
  csrf: string;
  expiresAt: number;
}

interface Claims {
  user_id?: string;
  sub?: string;
  email?: string;
  email_verified?: boolean;
  auth_time?: number;
  firebase?: { sign_in_provider?: string };
}

function claimsOf(idToken: string): Claims {
  const payload = idToken.split('.')[1] ?? '';
  return JSON.parse(Buffer.from(payload, 'base64url').toString('utf8')) as Claims;
}

function providerOf(claims: Claims): string {
  return claims.firebase?.sign_in_provider ?? '';
}

export class FakeApi {
  /** Seconds a sign-in stays fresh (KS_AUTH_MAX_AGE_SECONDS). */
  freshnessSeconds = 300;
  readonly users = new Map<string, User>(); // by Firebase uid
  readonly calls: string[] = [];
  private session: Session | null = null;

  async install(page: Page): Promise<void> {
    await page.route('**/api/v1/**', (route) => this.handle(route));
  }

  /** Marks the Demo identity of the current browser as past its 24 hours and ends its session. */
  expireCurrentDemo(): void {
    const user = this.currentUser();
    if (user) user.demoExpired = true;
    this.session = null;
  }

  userByEmail(email: string): User | undefined {
    return [...this.users.values()].find((u) => u.email === email);
  }

  private currentUser(): User | undefined {
    if (!this.session) return undefined;
    return [...this.users.values()].find((u) => u.id === this.session?.userId);
  }

  private identity(user: User, session: Session) {
    const department = DEPARTMENTS.find((d) => d.id === user.departmentId) ?? null;
    return {
      user_id: user.id,
      kind: user.kind,
      sign_in_provider: user.provider,
      email: user.email,
      display_name: null,
      active_department: department,
      csrf_token: session.csrf,
      expires_at: new Date(session.expiresAt).toISOString(),
    };
  }

  private newSession(user: User): Session {
    this.session = {
      userId: user.id,
      csrf: randomUUID(),
      expiresAt: Date.now() + 24 * 3600_000,
    };
    return this.session;
  }

  private error(route: Route, status: number, code: string) {
    return route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code, message: code, request_id: 'req_e2efake0001' } }),
    });
  }

  private json(route: Route, body: unknown, status = 200) {
    return route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  }

  private checkToken(claims: Claims, needsFresh: boolean): 'ok' | 'stale' {
    const age = Date.now() / 1000 - (claims.auth_time ?? 0);
    return needsFresh && age > this.freshnessSeconds ? 'stale' : 'ok';
  }

  private async handle(route: Route): Promise<void> {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api/, '');
    const key = `${request.method()} ${path}`;
    this.calls.push(key);
    const body = request.postData() ? (JSON.parse(request.postData() ?? '{}') as Record<string, string>) : {};
    const mutation = request.method() !== 'GET';

    // Cookie-authenticated mutations need the session CSRF token (AUTH-14).
    const sessionless = new Set(['POST /v1/auth/session', 'POST /v1/demo/start']);
    if (mutation && !sessionless.has(key)) {
      if (!this.session) return this.error(route, 401, 'UNAUTHENTICATED');
      if (request.headers()['x-csrf-token'] !== this.session.csrf) {
        return this.error(route, 403, 'CSRF_INVALID');
      }
    }

    switch (key) {
      case 'GET /v1/status':
        return this.json(route, { service: 'api', version: 'fake', environment: 'ci', database: 'ok' });
      case 'GET /v1/auth/me': {
        const user = this.currentUser();
        if (!user || !this.session) return this.error(route, 401, 'UNAUTHENTICATED');
        return this.json(route, this.identity(user, this.session));
      }
      case 'POST /v1/auth/session': {
        const claims = claimsOf(body['id_token'] ?? '');
        const provider = providerOf(claims);
        if (provider !== 'password' && provider !== 'google.com') {
          return this.error(route, 401, 'UNAUTHENTICATED');
        }
        if (!claims.email_verified) return this.error(route, 403, 'EMAIL_NOT_VERIFIED');
        if (this.checkToken(claims, true) === 'stale') return this.error(route, 401, 'REAUTH_REQUIRED');
        const uid = claims.user_id ?? claims.sub ?? '';
        let user = this.users.get(uid);
        if (!user) {
          user = {
            id: randomUUID(),
            uid,
            kind: 'registered',
            email: claims.email ?? null,
            provider,
            departmentId: null,
            demoExpired: false,
          };
          this.users.set(uid, user);
        } else if (user.kind === 'demo') {
          user.kind = 'registered'; // the exchange completes a pending conversion (AUTH-30, AUTH-34)
          user.email = claims.email ?? null;
          user.provider = provider;
        }
        return this.json(route, this.identity(user, this.newSession(user)));
      }
      case 'POST /v1/demo/start': {
        const claims = claimsOf(body['id_token'] ?? '');
        if (providerOf(claims) !== 'anonymous') return this.error(route, 401, 'UNAUTHENTICATED');
        const uid = claims.user_id ?? claims.sub ?? '';
        let user = this.users.get(uid);
        if (user?.demoExpired) return this.error(route, 401, 'DEMO_EXPIRED');
        if (!user) {
          user = {
            id: randomUUID(),
            uid,
            kind: 'demo',
            email: null,
            provider: 'anonymous',
            departmentId: null,
            demoExpired: false,
          };
          this.users.set(uid, user);
        }
        return this.json(route, this.identity(user, this.newSession(user)));
      }
      case 'POST /v1/auth/convert': {
        const user = this.currentUser();
        if (!user || user.kind !== 'demo') return this.error(route, 409, 'CONFLICT');
        const claims = claimsOf(body['id_token'] ?? '');
        const provider = providerOf(claims);
        if (provider === 'anonymous' || !claims.email_verified) {
          return this.error(route, 403, 'EMAIL_NOT_VERIFIED');
        }
        if ((claims.user_id ?? claims.sub) !== user.uid) return this.error(route, 409, 'CONFLICT');
        if (this.checkToken(claims, true) === 'stale') return this.error(route, 401, 'REAUTH_REQUIRED');
        user.kind = 'registered'; // same users.id and department: the history stays attached
        user.email = claims.email ?? null;
        user.provider = provider;
        return this.json(route, this.identity(user, this.newSession(user)));
      }
      case 'POST /v1/auth/logout':
        this.session = null;
        return route.fulfill({ status: 204 });
      case 'GET /v1/departments':
        if (!this.session) return this.error(route, 401, 'UNAUTHENTICATED');
        return this.json(route, { departments: DEPARTMENTS });
      case 'PUT /v1/session/department': {
        const user = this.currentUser();
        const department = DEPARTMENTS.find((d) => d.id === body['department_id']);
        if (!user || !this.session) return this.error(route, 401, 'UNAUTHENTICATED');
        if (!department) return this.error(route, 422, 'VALIDATION_ERROR');
        user.departmentId = department.id;
        return this.json(route, this.identity(user, this.session));
      }
      default:
        return this.error(route, 404, 'NOT_FOUND');
    }
  }
}

/** Installs the fake unless the run targets the real API. Returns the fake (or undefined). */
export async function useApi(page: Page): Promise<FakeApi | undefined> {
  if (REAL_API) return undefined;
  const api = new FakeApi();
  await api.install(page);
  return api;
}
