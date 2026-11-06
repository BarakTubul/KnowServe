import { screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  DEPARTMENTS_LIST,
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
import { AuthFlowError } from './gateway-types';
import { GENERIC_SIGN_IN_ERROR, SIGN_UP_NEUTRAL_MESSAGE } from './messages';

async function fillCredentials(
  user: ReturnType<typeof renderApp>['user'],
  email = 'ada@example.com',
  password = 'correct horse',
) {
  await user.type(screen.getByLabelText('Email'), email);
  await user.type(screen.getByLabelText('Password'), password);
}

describe('FE-AUTH-02 login screen', () => {
  it('fe_auth_02_login_screen_has_the_five_entries_and_no_otp', async () => {
    mockApi({ [ME]: unauthenticated });
    renderApp('/login');
    expect(await screen.findByTestId('login-page')).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeInTheDocument();
    expect(screen.getByLabelText('Password')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue with Google' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Forgot password?' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign up' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try Demo' })).toBeInTheDocument();
    expect(screen.queryByText(/otp|one-time|code by email/i)).not.toBeInTheDocument();
  });

  it('fe_auth_02_password_success_exchanges_the_token_and_opens_the_dashboard', async () => {
    const api = mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => jsonResponse(200, makeIdentity()),
    });
    const { user, gateway } = renderApp('/login');
    await screen.findByTestId('login-page');
    await fillCredentials(user);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(gateway.signInWithPassword).toHaveBeenCalledWith('ada@example.com', 'correct horse');
    const body = (await api.last(SESSION)?.json()) as { id_token: string };
    expect(body).toEqual({ id_token: 'fake-id-token' });
    expect(screen.getByTestId('location')).toHaveTextContent('/dashboard');
  });

  it('fe_auth_02_invalid_credential_shows_one_generic_message', async () => {
    mockApi({ [ME]: unauthenticated });
    const gateway = createFakeGateway();
    gateway.signInWithPassword.mockRejectedValueOnce(new AuthFlowError('invalid-credential'));
    const { user } = renderApp('/login', gateway);
    await screen.findByTestId('login-page');
    await fillCredentials(user, 'nobody@example.com', 'wrong password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(GENERIC_SIGN_IN_ERROR);
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument();
  });

  it('fe_auth_02_unverified_account_sees_the_verify_state_with_resend', async () => {
    mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => errorResponse(403, 'EMAIL_NOT_VERIFIED'),
    });
    const { user, gateway } = renderApp('/login');
    await screen.findByTestId('login-page');
    await fillCredentials(user);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    const panel = await screen.findByTestId('verify-email-panel');
    expect(within(panel).getByRole('heading', { name: 'Verify your email' })).toBeInTheDocument();
    await user.click(within(panel).getByRole('button', { name: 'Resend verification email' }));
    expect(gateway.resendVerification).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument();
  });

  it('fe_auth_02_google_success_opens_the_dashboard', async () => {
    mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => jsonResponse(200, makeIdentity({ sign_in_provider: 'google.com' })),
    });
    const { user, gateway } = renderApp('/login');
    await screen.findByTestId('login-page');
    await user.click(screen.getByRole('button', { name: 'Continue with Google' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(gateway.signInWithGoogle).toHaveBeenCalledTimes(1);
  });

  it('fe_auth_02_expired_session_returns_to_login_with_a_notice', async () => {
    mockApi({
      [ME]: () => jsonResponse(200, makeIdentity()),
      [DEPARTMENTS_LIST]: unauthenticated,
    });
    const { user } = renderApp('/dashboard');
    await screen.findByTestId('dashboard-page');
    await user.click(screen.getByRole('button', { name: 'Change department' }));
    expect(await screen.findByTestId('login-page')).toBeInTheDocument();
    expect(screen.getByText(/Your session ended/)).toBeInTheDocument();
  });

  it('fe_auth_02_reauth_required_asks_to_confirm_then_retries_exactly_once', async () => {
    let attempts = 0;
    const api = mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => {
        attempts += 1;
        return attempts === 1
          ? errorResponse(401, 'REAUTH_REQUIRED')
          : jsonResponse(200, makeIdentity());
      },
    });
    const { user, gateway } = renderApp('/login');
    await screen.findByTestId('login-page');
    await fillCredentials(user);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    const panel = await screen.findByTestId('reauth-panel');
    // Nothing is retried on its own: one call so far, and the user is asked.
    expect(api.count(SESSION)).toBe(1);
    expect(gateway.reauthenticateWithPassword).not.toHaveBeenCalled();
    await user.type(within(panel).getByLabelText('Password'), 'correct horse');
    await user.click(within(panel).getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(gateway.reauthenticateWithPassword).toHaveBeenCalledWith('correct horse');
    expect(api.count(SESSION)).toBe(2);
  });

  it('fe_auth_02_a_second_reauth_required_is_shown_not_retried_again', async () => {
    const api = mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => errorResponse(401, 'REAUTH_REQUIRED'),
    });
    const { user } = renderApp('/login');
    await screen.findByTestId('login-page');
    await fillCredentials(user);
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    const panel = await screen.findByTestId('reauth-panel');
    await user.type(within(panel).getByLabelText('Password'), 'correct horse');
    await user.click(within(panel).getByRole('button', { name: 'Confirm' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent(/still too old/);
    expect(api.count(SESSION)).toBe(2);
  });

  it('fe_auth_02_reauth_for_a_google_user_uses_the_google_popup', async () => {
    let attempts = 0;
    mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => {
        attempts += 1;
        return attempts === 1
          ? errorResponse(401, 'REAUTH_REQUIRED')
          : jsonResponse(200, makeIdentity({ sign_in_provider: 'google.com' }));
      },
    });
    const gateway = createFakeGateway();
    const { user } = renderApp('/login', gateway);
    await screen.findByTestId('login-page');
    await user.click(screen.getByRole('button', { name: 'Continue with Google' }));
    await screen.findByTestId('reauth-panel');
    await user.click(screen.getByRole('button', { name: 'Confirm with Google' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(gateway.reauthenticateWithGoogle).toHaveBeenCalledTimes(1);
  });
});

describe('FE-AUTH-03 signup', () => {
  async function openSignup() {
    mockApi({ [ME]: unauthenticated });
    const rendered = renderApp('/login');
    await screen.findByTestId('login-page');
    await rendered.user.click(screen.getByRole('button', { name: 'Sign up' }));
    return rendered;
  }

  it('fe_auth_03_seven_characters_is_an_inline_error_with_no_firebase_call', async () => {
    const { user, gateway } = await openSignup();
    await user.type(screen.getByLabelText('Email'), 'new@example.com');
    await user.type(screen.getByLabelText('Password'), 'abcdefg');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByTestId('password-error')).toHaveTextContent('at least 8');
    expect(gateway.signUpWithPassword).not.toHaveBeenCalled();
  });

  it('fe_auth_03_eight_lowercase_characters_are_accepted_and_the_check_email_state_shows', async () => {
    const { user, gateway } = await openSignup();
    await user.type(screen.getByLabelText('Email'), 'new@example.com');
    await user.type(screen.getByLabelText('Password'), 'abcdefgh');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(gateway.signUpWithPassword).toHaveBeenCalledWith('new@example.com', 'abcdefgh');
    const panel = await screen.findByTestId('verify-email-panel');
    expect(within(panel).getByRole('heading', { name: 'Check your email' })).toBeInTheDocument();
  });

  it('fe_auth_03_unicode_passphrase_is_accepted', async () => {
    const { user, gateway } = await openSignup();
    await user.type(screen.getByLabelText('Email'), 'new@example.com');
    await user.type(screen.getByLabelText('Password'), 'Zażółć gęślą jaźń 春夏秋冬');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    await waitFor(() => expect(gateway.signUpWithPassword).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('password-error')).not.toBeInTheDocument();
  });

  it('fe_auth_03_email_already_in_use_shows_a_neutral_message_pointing_to_sign_in_and_reset', async () => {
    mockApi({ [ME]: unauthenticated });
    const gateway = createFakeGateway();
    gateway.signUpWithPassword.mockRejectedValueOnce(new AuthFlowError('email-in-use'));
    const { user } = renderApp('/login', gateway);
    await screen.findByTestId('login-page');
    await user.click(screen.getByRole('button', { name: 'Sign up' }));
    await user.type(screen.getByLabelText('Email'), 'ada@example.com');
    await user.type(screen.getByLabelText('Password'), 'abcdefgh');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(SIGN_UP_NEUTRAL_MESSAGE);
    expect(alert).toHaveTextContent(/sign in/);
    expect(alert).toHaveTextContent(/reset your password/);
    expect(screen.queryByTestId('verify-email-panel')).not.toBeInTheDocument();
  });

  it('fe_auth_03_after_verifying_the_continue_button_starts_the_session', async () => {
    const api = mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => jsonResponse(200, makeIdentity()),
    });
    const gateway = createFakeGateway();
    const { user } = renderApp('/login', gateway);
    await screen.findByTestId('login-page');
    await user.click(screen.getByRole('button', { name: 'Sign up' }));
    await user.type(screen.getByLabelText('Email'), 'new@example.com');
    await user.type(screen.getByLabelText('Password'), 'abcdefgh');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    await screen.findByTestId('verify-email-panel');
    // Not verified yet: no session call.
    await user.click(screen.getByRole('button', { name: 'I have verified my email' }));
    expect(await screen.findByText(/not verified yet/)).toBeInTheDocument();
    expect(api.count(SESSION)).toBe(0);
    gateway.state.user = firebaseUser({ email: 'new@example.com', emailVerified: true });
    await user.click(screen.getByRole('button', { name: 'I have verified my email' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(gateway.getIdToken).toHaveBeenLastCalledWith(true);
  });
});
