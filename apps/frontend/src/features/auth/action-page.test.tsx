import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ME, SESSION, jsonResponse, makeIdentity, mockApi, unauthenticated } from '@/test/fake-api';
import { createFakeGateway, firebaseUser } from '@/test/fake-gateway';
import { renderApp } from '@/test/render';
import { AuthFlowError } from './gateway-types';
import { RESET_CONFIRMATION } from './messages';

const VERIFY = '/auth/action?mode=verifyEmail&oobCode=abc123';
const RESET = '/auth/action?mode=resetPassword&oobCode=abc123';

describe('FE-AUTH-07 verification action page', () => {
  it('fe_auth_07_verify_success_says_email_verified_and_starts_no_session', async () => {
    const api = mockApi({ [ME]: unauthenticated });
    const { gateway } = renderApp(VERIFY);
    const verified = await screen.findByTestId('action-verified');
    expect(within(verified).getByRole('heading', { name: 'Email verified' })).toBeInTheDocument();
    expect(gateway.applyVerificationCode).toHaveBeenCalledWith('abc123');
    expect(api.count(SESSION)).toBe(0);
    // Fresh browser (no Firebase user in this tab): the way on is the login screen.
    expect(within(verified).getByRole('link', { name: 'Go to sign in' })).toHaveAttribute(
      'href',
      '/login',
    );
    expect(screen.queryByTestId('reauth-panel')).not.toBeInTheDocument();
  });

  it('fe_auth_07_verify_expired_code_is_its_own_state', async () => {
    mockApi({ [ME]: unauthenticated });
    const gateway = createFakeGateway();
    gateway.applyVerificationCode.mockRejectedValueOnce(new AuthFlowError('expired-code'));
    renderApp(VERIFY, gateway);
    const expired = await screen.findByTestId('action-expired');
    expect(expired).toHaveTextContent('verification link has expired');
    expect(screen.queryByTestId('action-invalid')).not.toBeInTheDocument();
    expect(screen.queryByTestId('action-verified')).not.toBeInTheDocument();
  });

  it('fe_auth_07_verify_invalid_code_is_its_own_state', async () => {
    mockApi({ [ME]: unauthenticated });
    const gateway = createFakeGateway();
    gateway.applyVerificationCode.mockRejectedValueOnce(new AuthFlowError('invalid-code'));
    renderApp(VERIFY, gateway);
    const invalid = await screen.findByTestId('action-invalid');
    expect(invalid).toHaveTextContent('verification link is not valid');
    expect(screen.queryByTestId('action-expired')).not.toBeInTheDocument();
  });

  it('fe_auth_07_a_missing_code_or_unknown_mode_is_invalid', async () => {
    mockApi({ [ME]: unauthenticated });
    renderApp('/auth/action?mode=recoverEmail&oobCode=zzz');
    expect(await screen.findByTestId('action-invalid')).toBeInTheDocument();
  });

  it('fe_auth_07_the_code_is_applied_once_even_if_the_page_renders_again', async () => {
    mockApi({ [ME]: unauthenticated });
    const { gateway, rerender } = renderApp(VERIFY);
    await screen.findByTestId('action-verified');
    rerender(<></>);
    expect(gateway.applyVerificationCode).toHaveBeenCalledTimes(1);
  });

  it('fe_auth_07_verified_more_than_5_minutes_after_sign_in_in_the_same_tab_asks_to_confirm_the_credential', async () => {
    let attempts = 0;
    const api = mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => {
        attempts += 1;
        return jsonResponse(200, makeIdentity());
      },
    });
    const stale = firebaseUser({ emailVerified: false, lastSignInMs: Date.now() - 10 * 60_000 });
    const gateway = createFakeGateway(stale);
    const { user } = renderApp(VERIFY, gateway);
    const panel = await screen.findByTestId('reauth-panel');
    // Verification alone starts nothing.
    expect(api.count(SESSION)).toBe(0);
    await user.type(within(panel).getByLabelText('Password'), 'correct horse');
    await user.click(within(panel).getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(gateway.reauthenticateWithPassword).toHaveBeenCalledWith('correct horse');
    expect(attempts).toBe(1);
  });

  it('fe_auth_07_verified_soon_after_sign_in_in_the_same_tab_continues_on_an_explicit_click', async () => {
    const api = mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => jsonResponse(200, makeIdentity()),
    });
    const gateway = createFakeGateway(firebaseUser({ emailVerified: false }));
    const { user } = renderApp(VERIFY, gateway);
    const verified = await screen.findByTestId('action-verified');
    expect(api.count(SESSION)).toBe(0);
    await user.click(within(verified).getByRole('button', { name: 'Continue to KnowServe' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(api.count(SESSION)).toBe(1);
  });
});

describe('FE-AUTH-07 and FE-AUTH-11 reset', () => {
  it('fe_auth_07_reset_success_shows_the_new_password_form_then_a_done_state', async () => {
    mockApi({ [ME]: unauthenticated });
    const { user, gateway } = renderApp(RESET);
    const form = await screen.findByTestId('action-reset-form');
    expect(gateway.verifyResetCode).toHaveBeenCalledWith('abc123');
    await user.type(within(form).getByLabelText('New password'), 'a brand new passphrase');
    await user.click(within(form).getByRole('button', { name: 'Change password' }));
    expect(await screen.findByTestId('action-reset-done')).toBeInTheDocument();
    expect(gateway.confirmPasswordReset).toHaveBeenCalledWith('abc123', 'a brand new passphrase');
  });

  it('fe_auth_07_reset_new_password_needs_8_characters', async () => {
    mockApi({ [ME]: unauthenticated });
    const { user, gateway } = renderApp(RESET);
    const form = await screen.findByTestId('action-reset-form');
    await user.type(within(form).getByLabelText('New password'), 'short');
    await user.click(within(form).getByRole('button', { name: 'Change password' }));
    expect(await screen.findByTestId('password-error')).toBeInTheDocument();
    expect(gateway.confirmPasswordReset).not.toHaveBeenCalled();
  });

  it('fe_auth_07_reset_expired_and_invalid_are_distinct_and_offer_a_new_request', async () => {
    mockApi({ [ME]: unauthenticated });
    const expiredGateway = createFakeGateway();
    expiredGateway.verifyResetCode.mockRejectedValueOnce(new AuthFlowError('expired-code'));
    const first = renderApp(RESET, expiredGateway);
    expect(await screen.findByTestId('action-expired')).toHaveTextContent('reset link has expired');
    expect(screen.getByRole('button', { name: 'Request a new reset link' })).toBeInTheDocument();
    first.unmount();

    const invalidGateway = createFakeGateway();
    invalidGateway.verifyResetCode.mockRejectedValueOnce(new AuthFlowError('invalid-code'));
    renderApp(RESET, invalidGateway);
    expect(await screen.findByTestId('action-invalid')).toHaveTextContent(
      'reset link is not valid',
    );
    expect(screen.queryByTestId('action-expired')).not.toBeInTheDocument();
  });

  it('fe_auth_07_a_code_spent_between_check_and_submit_becomes_the_invalid_state', async () => {
    mockApi({ [ME]: unauthenticated });
    const gateway = createFakeGateway();
    gateway.confirmPasswordReset.mockRejectedValueOnce(new AuthFlowError('invalid-code'));
    const { user } = renderApp(RESET, gateway);
    const form = await screen.findByTestId('action-reset-form');
    await user.type(within(form).getByLabelText('New password'), 'a brand new passphrase');
    await user.click(within(form).getByRole('button', { name: 'Change password' }));
    expect(await screen.findByTestId('action-invalid')).toBeInTheDocument();
  });

  async function requestReset(email: string, gateway = createFakeGateway()) {
    mockApi({ [ME]: unauthenticated });
    const rendered = renderApp('/login', gateway);
    await screen.findByTestId('login-page');
    await rendered.user.click(screen.getByRole('button', { name: 'Forgot password?' }));
    await rendered.user.type(screen.getByLabelText('Email'), email);
    await rendered.user.click(screen.getByRole('button', { name: 'Send reset link' }));
    const text = (await screen.findByTestId('reset-confirmation')).textContent;
    rendered.unmount();
    return text;
  }

  it('fe_auth_11_reset_request_shows_the_same_confirmation_for_a_known_and_an_unknown_email', async () => {
    const known = await requestReset('ada@example.com');
    const unknownGateway = createFakeGateway();
    unknownGateway.sendPasswordReset.mockRejectedValueOnce(new AuthFlowError('invalid-credential'));
    const unknown = await requestReset('nobody@example.com', unknownGateway);
    expect(known).toBe(RESET_CONFIRMATION);
    expect(unknown).toBe(known);
    expect(unknownGateway.sendPasswordReset).toHaveBeenCalledWith('nobody@example.com');
  });
});
