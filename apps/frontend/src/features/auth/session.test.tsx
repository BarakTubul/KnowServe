import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import { getCsrfToken } from '@/lib/api/csrf';
import {
  DEPARTMENTS_LIST,
  LOGOUT,
  ME,
  errorResponse,
  jsonResponse,
  makeIdentity,
  mockApi,
  unauthenticated,
} from '@/test/fake-api';
import { createFakeGateway } from '@/test/fake-gateway';
import { renderApp } from '@/test/render';
import { AuthProvider } from './auth-provider';
import { useAuth } from './auth-context';

const CSRF = 'csrf-value-that-must-stay-in-memory';

describe('FE-AUTH-01 hydration from the current-identity endpoint', () => {
  it('fe_auth_01_pending_identity_shows_a_loader_and_no_protected_content_or_redirect', async () => {
    mockApi({ [ME]: () => new Promise<Response>(() => {}) });
    renderApp('/dashboard');
    expect(await screen.findByTestId('auth-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/dashboard');
  });

  it('fe_auth_01_identity_200_sets_the_state_and_shows_the_protected_screen', async () => {
    mockApi({ [ME]: () => jsonResponse(200, makeIdentity({ csrf_token: CSRF })) });
    renderApp('/dashboard');
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(screen.getByTestId('active-department')).toHaveTextContent('Aurora Finance');
    expect(getCsrfToken()).toBe(CSRF);
  });

  it('fe_auth_01_identity_401_goes_to_the_public_view_without_a_protected_flash', async () => {
    mockApi({ [ME]: unauthenticated });
    renderApp('/dashboard');
    expect(await screen.findByTestId('login-page')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/login');
    expect(getCsrfToken()).toBeNull();
  });

  it('fe_arch_06_a_signed_in_user_is_sent_from_login_to_the_dashboard', async () => {
    mockApi({ [ME]: () => jsonResponse(200, makeIdentity()) });
    renderApp('/login');
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
  });
});

/** Cached queries of the signed-in user; the public entry page's own status query is not one of them. */
function scopedQueries(client: {
  getQueryCache(): { getAll(): { queryKey: readonly unknown[] }[] };
}) {
  return client
    .getQueryCache()
    .getAll()
    .filter((q) => q.queryKey[0] === 'identity' || q.queryKey[0] === 'dept');
}

describe('FE-AUTH-04 logout', () => {
  it('fe_auth_04_logout_calls_the_api_signs_out_of_firebase_clears_the_cache_and_goes_to_the_entry', async () => {
    const api = mockApi({
      [ME]: () => jsonResponse(200, makeIdentity({ csrf_token: CSRF })),
      [LOGOUT]: () => new Response(null, { status: 204 }),
    });
    const { user, client, gateway } = renderApp('/dashboard');
    await screen.findByTestId('dashboard-page');
    client.setQueryData(['dept', 'u', 'd', 'documents'], ['secret']);
    client.setQueryData(['identity', 'u', 'departments'], ['x']);
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    await screen.findByTestId('status-page');
    expect(api.count(LOGOUT)).toBe(1);
    expect(api.last(LOGOUT)?.headers.get('X-CSRF-Token')).toBe(CSRF);
    expect(gateway.signOut).toHaveBeenCalledTimes(1);
    expect(scopedQueries(client)).toHaveLength(0);
    expect(screen.getByTestId('location')).toHaveTextContent('/');
    expect(getCsrfToken()).toBeNull();
  });

  it('fe_auth_04_logout_still_clears_everything_when_the_api_call_fails', async () => {
    mockApi({
      [ME]: () => jsonResponse(200, makeIdentity()),
      [LOGOUT]: () => errorResponse(500, 'INTERNAL_ERROR'),
    });
    const { user, client, gateway } = renderApp('/dashboard');
    await screen.findByTestId('dashboard-page');
    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    await screen.findByTestId('status-page');
    expect(gateway.signOut).toHaveBeenCalledTimes(1);
    expect(scopedQueries(client)).toHaveLength(0);
  });
});

describe('FE-AUTH-05 global API error handling', () => {
  async function openDepartments(departments: () => Response | Promise<Response>) {
    mockApi({ [ME]: () => jsonResponse(200, makeIdentity()), [DEPARTMENTS_LIST]: departments });
    const rendered = renderApp('/dashboard');
    await screen.findByTestId('dashboard-page');
    await rendered.user.click(screen.getByRole('button', { name: 'Change department' }));
    return rendered;
  }

  it('fe_auth_05_a_401_from_a_query_clears_the_identity_cache_and_redirects_to_login', async () => {
    const { client } = await openDepartments(() => errorResponse(401, 'UNAUTHENTICATED'));
    expect(await screen.findByTestId('login-page')).toBeInTheDocument();
    expect(screen.getByTestId('location')).toHaveTextContent('/login');
    expect(client.getQueryCache().getAll()).toHaveLength(0);
    expect(getCsrfToken()).toBeNull();
  });

  it('fe_auth_05_a_429_shows_the_retry_time_and_keeps_the_user_signed_in', async () => {
    await openDepartments(() =>
      errorResponse(429, 'QUOTA_EXCEEDED', 'quota', { 'Retry-After': '7200' }),
    );
    const notice = await screen.findByTestId('api-notice-quota');
    expect(notice).toHaveTextContent('Try again in 2 hours');
    expect(screen.getByTestId('dashboard-page')).toBeInTheDocument();
    expect(getCsrfToken()).toBe('csrf-token-from-api');
  });

  it('fe_auth_05_rate_limited_without_retry_after_still_gives_a_clear_message', async () => {
    await openDepartments(() => errorResponse(429, 'RATE_LIMITED'));
    const notice = await screen.findByTestId('api-notice-rate-limited');
    expect(notice).toHaveTextContent('Try again later');
    expect(screen.getByTestId('dashboard-page')).toBeInTheDocument();
  });

  it('fe_auth_05_a_503_ai_unavailable_shows_the_degraded_message_and_the_app_stays_usable', async () => {
    const { user } = await openDepartments(() => errorResponse(503, 'AI_UNAVAILABLE'));
    expect(await screen.findByTestId('api-notice-ai-unavailable')).toHaveTextContent(
      /temporarily unavailable.*browse your documents/s,
    );
    expect(screen.getByTestId('dashboard-page')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(screen.queryByTestId('api-notice-ai-unavailable')).not.toBeInTheDocument();
  });

  it('fe_auth_05_a_reauth_required_401_is_not_treated_as_a_lost_session', async () => {
    await openDepartments(() => errorResponse(401, 'REAUTH_REQUIRED'));
    expect(screen.getByTestId('dashboard-page')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });
});

describe('FE-AUTH-06 no credentials in web storage', () => {
  afterEach(() => {
    globalThis.sessionStorage.clear();
    globalThis.localStorage.clear();
  });

  function storageDump(): string {
    const entries: string[] = [];
    for (const store of [globalThis.localStorage, globalThis.sessionStorage]) {
      for (let i = 0; i < store.length; i += 1) {
        const key = store.key(i) ?? '';
        entries.push(`${key}=${store.getItem(key) ?? ''}`);
      }
    }
    return entries.join('\n');
  }

  it('fe_auth_06_after_login_no_session_csrf_or_token_value_is_in_web_storage', async () => {
    mockApi({
      [ME]: unauthenticated,
      'POST /v1/auth/session': () => jsonResponse(200, makeIdentity({ csrf_token: CSRF })),
    });
    const { user } = renderApp('/login');
    await screen.findByTestId('login-page');
    await user.type(screen.getByLabelText('Email'), 'ada@example.com');
    await user.type(screen.getByLabelText('Password'), 'correct horse');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    await screen.findByTestId('dashboard-page');
    const dump = storageDump();
    expect(dump).not.toContain(CSRF);
    expect(dump).not.toContain('fake-id-token');
    expect(dump).not.toContain('correct horse');
    expect(dump).not.toMatch(/csrf|ks_session|session_id|id_token/i);
  });
});

describe('FE-ARCH-04 identity change', () => {
  function Switcher() {
    const { applyIdentity } = useAuth();
    return (
      <button
        type="button"
        onClick={() =>
          applyIdentity(makeIdentity({ user_id: '88888888-8888-4888-8888-888888888888' }))
        }
      >
        become another user
      </button>
    );
  }

  it('fe_arch_04_a_different_user_never_sees_the_previous_users_cache', async () => {
    mockApi({ [ME]: () => jsonResponse(200, makeIdentity()) });
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <AuthProvider gateway={createFakeGateway()}>
            <Switcher />
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await screen.findByRole('button', { name: 'become another user' });
    // Wait for the first identity to be applied (the hydration call).
    await new Promise((resolve) => setTimeout(resolve, 20));
    client.setQueryData(['dept', 'old-user', 'dep', 'documents'], ['private']);
    await user.click(screen.getByRole('button', { name: 'become another user' }));
    expect(client.getQueryCache().getAll()).toHaveLength(0);
  });
});
