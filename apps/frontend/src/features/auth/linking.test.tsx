import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ME, SESSION, jsonResponse, makeIdentity, mockApi, unauthenticated } from '@/test/fake-api';
import { createFakeGateway } from '@/test/fake-gateway';
import { renderApp } from '@/test/render';
import { AuthFlowError } from './gateway-types';

async function googleHitsPasswordAccount(gateway = createFakeGateway()) {
  gateway.signInWithGoogle.mockRejectedValueOnce(
    new AuthFlowError('account-exists', 'ada@example.com'),
  );
  const rendered = renderApp('/login', gateway);
  await screen.findByTestId('login-page');
  await rendered.user.click(screen.getByRole('button', { name: 'Continue with Google' }));
  return rendered;
}

describe('FE-AUTH-12 account linking', () => {
  it('fe_auth_12_google_hitting_a_password_account_asks_for_the_password_first_and_links_nothing_yet', async () => {
    const api = mockApi({ [ME]: unauthenticated });
    const { gateway } = await googleHitsPasswordAccount();
    const panel = await screen.findByTestId('link-account');
    expect(panel).toHaveTextContent('ada@example.com already has a password account');
    expect(panel).toHaveTextContent('Sign in with that password first');
    expect(gateway.linkPendingGoogle).not.toHaveBeenCalled();
    expect(api.count(SESSION)).toBe(0);
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument();
  });

  it('fe_auth_12_after_the_password_the_credential_is_linked_and_a_session_starts', async () => {
    const api = mockApi({
      [ME]: unauthenticated,
      [SESSION]: () => jsonResponse(200, makeIdentity()),
    });
    const { user, gateway } = await googleHitsPasswordAccount();
    const panel = await screen.findByTestId('link-account');
    await user.type(within(panel).getByLabelText(/Password for/), 'correct horse');
    await user.click(within(panel).getByRole('button', { name: 'Sign in and link Google' }));
    expect(await screen.findByTestId('dashboard-page')).toBeInTheDocument();
    expect(gateway.linkPendingGoogle).toHaveBeenCalledWith('ada@example.com', 'correct horse');
    expect(api.count(SESSION)).toBe(1);
  });

  it('fe_auth_12_an_unverified_password_account_is_never_linked', async () => {
    const api = mockApi({ [ME]: unauthenticated });
    const gateway = createFakeGateway();
    gateway.linkPendingGoogle.mockRejectedValueOnce(new AuthFlowError('unverified'));
    const { user } = await googleHitsPasswordAccount(gateway);
    const panel = await screen.findByTestId('link-account');
    await user.type(within(panel).getByLabelText(/Password for/), 'correct horse');
    await user.click(within(panel).getByRole('button', { name: 'Sign in and link Google' }));
    const blocked = await screen.findByTestId('link-unverified');
    expect(blocked).toHaveTextContent('has not been verified');
    expect(within(blocked).queryByRole('button', { name: /link/i })).not.toBeInTheDocument();
    expect(api.count(SESSION)).toBe(0);
  });

  it('fe_auth_12_a_wrong_password_shows_the_generic_error_and_does_not_link', async () => {
    mockApi({ [ME]: unauthenticated });
    const gateway = createFakeGateway();
    gateway.linkPendingGoogle.mockRejectedValueOnce(new AuthFlowError('invalid-credential'));
    const { user } = await googleHitsPasswordAccount(gateway);
    const panel = await screen.findByTestId('link-account');
    await user.type(within(panel).getByLabelText(/Password for/), 'nope nope nope');
    await user.click(within(panel).getByRole('button', { name: 'Sign in and link Google' }));
    expect(await within(panel).findByRole('alert')).toHaveTextContent(
      'The email or password is not correct.',
    );
    expect(screen.queryByTestId('dashboard-page')).not.toBeInTheDocument();
  });

  it('fe_auth_12_cancel_drops_the_pending_google_credential', async () => {
    mockApi({ [ME]: unauthenticated });
    const { user, gateway } = await googleHitsPasswordAccount();
    const panel = await screen.findByTestId('link-account');
    await user.click(within(panel).getByRole('button', { name: 'Cancel' }));
    expect(gateway.cancelPendingLink).toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'Continue with Google' })).toBeInTheDocument();
  });

  it('fe_auth_12_the_admin_has_no_special_sign_in_ui', async () => {
    // Admin rights come only from the server (AUTH-04): the login screen has no admin entry.
    mockApi({ [ME]: unauthenticated });
    renderApp('/login');
    await screen.findByTestId('login-page');
    expect(screen.queryByText(/admin/i)).not.toBeInTheDocument();
  });
});
