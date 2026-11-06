import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AuthFlowError } from '@/features/auth/gateway-types';
import {
  CONVERT,
  DEMO_START,
  ME,
  SESSION,
  errorResponse,
  jsonResponse,
  makeIdentity,
  mockApi,
  unauthenticated,
} from '@/test/fake-api';
import { createFakeGateway, firebaseUser } from '@/test/fake-gateway';
import { renderApp } from '@/test/render';
import { formatTimeLeft } from './demo-mode-indicator';

const DEMO_CSRF = 'demo-csrf';
const demoIdentity = (over = {}) =>
  makeIdentity({
    kind: 'demo',
    sign_in_provider: 'anonymous',
    email: null,
    csrf_token: DEMO_CSRF,
    expires_at: new Date(Date.now() + 5 * 3600_000 + 30 * 60_000).toISOString(),
    ...over,
  });

describe('FE-AUTH-08 Try Demo', () => {
  it('fe_auth_08_try_demo_signs_in_anonymously_starts_the_demo_and_shows_mode_and_time_left', async () => {
    const api = mockApi({
      [ME]: unauthenticated,
      [DEMO_START]: () => jsonResponse(200, demoIdentity()),
    });
    const { user, gateway } = renderApp('/login');
    await screen.findByTestId('login-page');
    await user.click(screen.getByRole('button', { name: 'Try Demo' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(gateway.signInAnonymously).toHaveBeenCalledTimes(1);
    expect(await api.last(DEMO_START)?.json()).toEqual({ id_token: 'fake-id-token' });
    expect(screen.getByTestId('demo-mode-badge')).toHaveTextContent('Demo Mode');
    expect(screen.getByTestId('demo-time-left')).toHaveTextContent('5 h 29 min left');
    expect(screen.getByTestId('account-kind')).toHaveTextContent('Demo visitor');
  });

  it('fe_auth_08_a_reload_stays_in_demo_through_the_identity_endpoint', async () => {
    mockApi({ [ME]: () => jsonResponse(200, demoIdentity()) });
    renderApp('/dashboard');
    expect(await screen.findByTestId('account-kind')).toHaveTextContent('Demo visitor');
    expect(screen.getByTestId('demo-time-left')).toBeInTheDocument();
  });

  it('fe_auth_08_demo_expired_signs_out_of_firebase_and_starts_a_new_demo', async () => {
    let attempts = 0;
    const api = mockApi({
      [ME]: unauthenticated,
      [DEMO_START]: () => {
        attempts += 1;
        return attempts === 1
          ? errorResponse(401, 'DEMO_EXPIRED')
          : jsonResponse(200, demoIdentity());
      },
    });
    const { user, gateway } = renderApp('/login');
    await screen.findByTestId('login-page');
    await user.click(screen.getByRole('button', { name: 'Try Demo' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(gateway.signOut).toHaveBeenCalledTimes(1);
    expect(gateway.signInAnonymously).toHaveBeenCalledTimes(2);
    expect(api.count(DEMO_START)).toBe(2);
  });

  it('fe_auth_08_a_rate_limited_demo_start_shows_the_retry_time_on_the_login_screen', async () => {
    mockApi({
      [ME]: unauthenticated,
      [DEMO_START]: () => errorResponse(429, 'RATE_LIMITED', 'slow', { 'Retry-After': '90' }),
    });
    const { user } = renderApp('/login');
    await screen.findByTestId('login-page');
    await user.click(screen.getByRole('button', { name: 'Try Demo' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Try again in 2 minutes');
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument();
  });

  it('fe_auth_08_time_left_formatting', () => {
    expect(formatTimeLeft(30_000)).toBe('less than a minute');
    expect(formatTimeLeft(45 * 60_000)).toBe('45 min');
    expect(formatTimeLeft(3 * 3600_000 + 5 * 60_000)).toBe('3 h 5 min');
  });
});

describe('FE-AUTH-13 create an account from a Demo', () => {
  const REGISTERED = () =>
    makeIdentity({ kind: 'registered', email: 'new@example.com', csrf_token: 'new-csrf' });

  async function openDemo(
    gateway = createFakeGateway(
      firebaseUser({
        uid: 'anon-1',
        isAnonymous: true,
        email: null,
        emailVerified: false,
        providerIds: [],
      }),
    ),
    routes: Record<string, () => Response> = {},
  ) {
    const api = mockApi({
      [ME]: () => jsonResponse(200, demoIdentity()),
      [CONVERT]: () => jsonResponse(200, REGISTERED()),
      ...routes,
    });
    const rendered = renderApp('/dashboard', gateway);
    await screen.findByTestId('create-account');
    return { ...rendered, api };
  }

  it('fe_auth_13_the_ui_says_the_history_is_kept', async () => {
    await openDemo();
    expect(screen.getByTestId('create-account')).toHaveTextContent('history and departments move');
  });

  it('fe_auth_13_password_signup_stays_in_demo_with_a_pending_state_until_verified_then_converts', async () => {
    const { user, gateway, api } = await openDemo();
    await user.type(screen.getByLabelText('Email'), 'new@example.com');
    await user.type(screen.getByLabelText('Password'), 'correct horse');
    await user.click(screen.getByRole('button', { name: 'Create account with email' }));
    const pending = await screen.findByTestId('convert-pending');
    expect(gateway.linkEmailPassword).toHaveBeenCalledWith('new@example.com', 'correct horse');
    expect(api.count(CONVERT)).toBe(0);
    expect(screen.getByTestId('account-kind')).toHaveTextContent('Demo visitor');

    // Not verified yet: the check does not convert.
    await user.click(within(pending).getByRole('button', { name: 'I have verified my email' }));
    expect(await screen.findByText(/not verified yet/)).toBeInTheDocument();
    expect(api.count(CONVERT)).toBe(0);

    // Verified elsewhere, then the explicit check: fresh token, then the conversion with the Demo CSRF token.
    gateway.state.user = firebaseUser({ email: 'new@example.com', emailVerified: true });
    await user.click(within(pending).getByRole('button', { name: 'I have verified my email' }));
    expect(await screen.findByTestId('registered-state')).toHaveTextContent(
      'Demo history and departments are kept',
    );
    expect(api.count(CONVERT)).toBe(1);
    expect(api.last(CONVERT)?.headers.get('X-CSRF-Token')).toBe(DEMO_CSRF);
    expect(gateway.getIdToken).toHaveBeenLastCalledWith(true);
    expect(screen.getByTestId('account-kind')).toHaveTextContent('Registered (new@example.com)');
    expect(screen.queryByTestId('create-account')).not.toBeInTheDocument();
  });

  it('fe_auth_13_the_pending_state_survives_a_reload', async () => {
    // After a reload the KnowServe session is still Demo and Firebase still holds the linked, unverified user.
    const gateway = createFakeGateway(
      firebaseUser({
        uid: 'anon-1',
        email: 'new@example.com',
        emailVerified: false,
        providerIds: ['password'],
      }),
    );
    mockApi({ [ME]: () => jsonResponse(200, demoIdentity()) });
    renderApp('/dashboard', gateway);
    expect(await screen.findByTestId('convert-pending')).toHaveTextContent('new@example.com');
  });

  it('fe_auth_13_resend_sends_the_verification_email_again', async () => {
    const gateway = createFakeGateway(
      firebaseUser({ email: 'new@example.com', emailVerified: false }),
    );
    const { user } = await openDemo(gateway);
    await user.click(await screen.findByRole('button', { name: 'Resend verification email' }));
    expect(gateway.resendVerification).toHaveBeenCalledTimes(1);
  });

  it('fe_auth_13_google_converts_at_once', async () => {
    const { user, gateway, api } = await openDemo();
    await user.click(screen.getByRole('button', { name: 'Continue with Google' }));
    expect(await screen.findByTestId('registered-state')).toBeInTheDocument();
    expect(gateway.linkGoogle).toHaveBeenCalledTimes(1);
    expect(api.count(CONVERT)).toBe(1);
  });

  it('fe_auth_13_an_email_already_registered_explains_no_merge_and_offers_sign_in', async () => {
    const gateway = createFakeGateway(
      firebaseUser({ isAnonymous: true, email: null, emailVerified: false, providerIds: [] }),
    );
    gateway.linkEmailPassword.mockRejectedValueOnce(new AuthFlowError('email-in-use'));
    const { user, api } = await openDemo(gateway, {
      'POST /v1/auth/logout': () => new Response(null, { status: 204 }),
    });
    await user.type(screen.getByLabelText('Email'), 'ada@example.com');
    await user.type(screen.getByLabelText('Password'), 'correct horse');
    await user.click(screen.getByRole('button', { name: 'Create account with email' }));
    const collision = await screen.findByTestId('convert-collision');
    expect(collision).toHaveTextContent('Demo history will not be moved');
    expect(collision).toHaveTextContent('nothing is merged');
    expect(api.count(CONVERT)).toBe(0);
    await user.click(within(collision).getByRole('button', { name: /Sign in to that account/ }));
    expect(await screen.findByTestId('login-page')).toBeInTheDocument();
    expect(gateway.signOut).toHaveBeenCalled();
  });

  it('fe_auth_13_a_google_account_already_linked_elsewhere_gets_the_same_explanation', async () => {
    const gateway = createFakeGateway(
      firebaseUser({ isAnonymous: true, email: null, emailVerified: false, providerIds: [] }),
    );
    gateway.linkGoogle.mockRejectedValueOnce(new AuthFlowError('credential-in-use'));
    const { user } = await openDemo(gateway);
    await user.click(screen.getByRole('button', { name: 'Continue with Google' }));
    expect(await screen.findByTestId('convert-collision')).toHaveTextContent(
      'Demo history will not be moved',
    );
  });

  it('fe_auth_13_keep_using_demo_returns_to_the_form_without_signing_out', async () => {
    const gateway = createFakeGateway(
      firebaseUser({ isAnonymous: true, email: null, emailVerified: false, providerIds: [] }),
    );
    gateway.linkGoogle.mockRejectedValueOnce(new AuthFlowError('credential-in-use'));
    const { user } = await openDemo(gateway);
    await user.click(screen.getByRole('button', { name: 'Continue with Google' }));
    await user.click(await screen.findByRole('button', { name: 'Keep using Demo' }));
    expect(screen.getByRole('button', { name: 'Create account with email' })).toBeInTheDocument();
    expect(gateway.signOut).not.toHaveBeenCalled();
  });

  it('fe_auth_13_a_stale_sign_in_at_conversion_asks_to_confirm_then_retries_once', async () => {
    let attempts = 0;
    const gateway = createFakeGateway(
      firebaseUser({ isAnonymous: true, email: null, emailVerified: false, providerIds: [] }),
    );
    // Linked and verified but the sign-in is old: the API says REAUTH_REQUIRED.
    const { user, api } = await openDemo(gateway, {
      [CONVERT]: () => {
        attempts += 1;
        return attempts === 1
          ? errorResponse(401, 'REAUTH_REQUIRED')
          : jsonResponse(200, REGISTERED());
      },
    });
    // The signed-in Firebase user is verified, but the app is still Demo: finish through the check button.
    gateway.state.user = firebaseUser({ email: 'new@example.com', emailVerified: false });
    await user.type(screen.getByLabelText('Email'), 'new@example.com');
    await user.type(screen.getByLabelText('Password'), 'correct horse');
    await user.click(screen.getByRole('button', { name: 'Create account with email' }));
    await user.click(await screen.findByRole('button', { name: 'I have verified my email' }));
    // (reloadUser reports the user still unverified, so set it verified and press again)
    gateway.state.user = firebaseUser({ email: 'new@example.com', emailVerified: true });
    await user.click(screen.getByRole('button', { name: 'I have verified my email' }));
    const panel = await screen.findByTestId('reauth-panel');
    expect(api.count(CONVERT)).toBe(1);
    await user.type(within(panel).getByLabelText('Password'), 'correct horse');
    await user.click(within(panel).getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByTestId('registered-state')).toBeInTheDocument();
    expect(api.count(CONVERT)).toBe(2);
    expect(api.count(SESSION)).toBe(0);
  });
});
