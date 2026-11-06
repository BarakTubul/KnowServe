import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { departmentKey } from '@/features/auth/auth-context';
import {
  DEPARTMENTS,
  DEPARTMENTS_LIST,
  ME,
  SET_DEPARTMENT,
  departmentsOk,
  errorResponse,
  jsonResponse,
  makeIdentity,
  mockApi,
} from '@/test/fake-api';
import { renderApp } from '@/test/render';

const [A, B, C] = DEPARTMENTS;
if (!A || !B || !C) throw new Error('fixture needs three departments');

describe('FE-AUTH-09 department selection', () => {
  it('fe_auth_09_first_login_has_no_department_so_the_selector_is_required_and_lists_every_api_department', async () => {
    mockApi({
      [ME]: () => jsonResponse(200, makeIdentity({ active_department: null })),
      [DEPARTMENTS_LIST]: departmentsOk,
    });
    renderApp('/dashboard');
    const required = await screen.findByTestId('department-required');
    expect(screen.queryByTestId('active-department')).not.toBeInTheDocument();
    // Names come from the API fixture (invented ones), proving nothing is hard-coded (FE-ARCH-13).
    for (const department of DEPARTMENTS) {
      expect(await within(required).findByRole('button', { name: department.name })).toBeEnabled();
    }
    expect(within(required).queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
    expect(required).toHaveTextContent('Demo Mode');
    expect(required).toHaveTextContent('never gives you extra access');
  });

  it('fe_auth_09_choosing_a_department_calls_the_api_with_csrf_and_shows_it', async () => {
    const api = mockApi({
      [ME]: () => jsonResponse(200, makeIdentity({ active_department: null })),
      [DEPARTMENTS_LIST]: departmentsOk,
      [SET_DEPARTMENT]: () => jsonResponse(200, makeIdentity({ active_department: B })),
    });
    const { user } = renderApp('/dashboard');
    await user.click(await screen.findByRole('button', { name: B.name }));
    expect(await screen.findByTestId('active-department')).toHaveTextContent(B.name);
    const request = api.last(SET_DEPARTMENT);
    expect(await request?.json()).toEqual({ department_id: B.id });
    expect(request?.headers.get('X-CSRF-Token')).toBe('csrf-token-from-api');
    expect(request?.credentials).toBe('include');
    expect(screen.queryByTestId('department-required')).not.toBeInTheDocument();
  });

  it('fe_auth_09_a_later_login_restores_the_last_department_from_the_identity', async () => {
    mockApi({ [ME]: () => jsonResponse(200, makeIdentity({ active_department: C })) });
    renderApp('/dashboard');
    expect(await screen.findByTestId('active-department')).toHaveTextContent(C.name);
    expect(screen.queryByTestId('department-required')).not.toBeInTheDocument();
  });

  it('fe_auth_09_every_api_department_is_selectable_when_switching', async () => {
    mockApi({
      [ME]: () => jsonResponse(200, makeIdentity({ active_department: A })),
      [DEPARTMENTS_LIST]: departmentsOk,
    });
    const { user } = renderApp('/dashboard');
    await user.click(await screen.findByRole('button', { name: 'Change department' }));
    const dialog = await screen.findByRole('dialog');
    for (const department of DEPARTMENTS) {
      expect(await within(dialog).findByRole('button', { name: department.name })).toBeEnabled();
    }
    expect(within(dialog).getByRole('button', { name: A.name })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('fe_auth_09_a_409_active_department_required_opens_the_selector', async () => {
    let departmentCalls = 0;
    mockApi({
      [ME]: () => jsonResponse(200, makeIdentity({ active_department: A })),
      // Any department-scoped call that answers 409 must open the selector, not show a generic error.
      [DEPARTMENTS_LIST]: () => {
        departmentCalls += 1;
        return errorResponse(409, 'ACTIVE_DEPARTMENT_REQUIRED');
      },
    });
    const { user } = renderApp('/dashboard');
    await screen.findByTestId('dashboard-page');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Change department' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(departmentCalls).toBeGreaterThan(0);
    expect(screen.queryByText(/Something went wrong/)).not.toBeInTheDocument();
  });
});

describe('FE-ARCH-04 department switch resets department-scoped cache', () => {
  it('fe_arch_04_switching_a_to_b_removes_a_scoped_data_and_uses_new_keys', async () => {
    mockApi({
      [ME]: () => jsonResponse(200, makeIdentity({ active_department: A })),
      [DEPARTMENTS_LIST]: departmentsOk,
      [SET_DEPARTMENT]: () => jsonResponse(200, makeIdentity({ active_department: B })),
    });
    const { user, client } = renderApp('/dashboard');
    const before = makeIdentity({ active_department: A });
    await screen.findByTestId('active-department');
    client.setQueryData(departmentKey(before, 'documents'), ['A-only document']);
    client.setQueryData(departmentKey(before, 'chats'), ['A-only chat']);
    await user.click(screen.getByRole('button', { name: 'Change department' }));
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByRole('button', { name: B.name }));
    expect(await screen.findByTestId('active-department')).toHaveTextContent(B.name);
    expect(client.getQueryData(departmentKey(before, 'documents'))).toBeUndefined();
    expect(client.getQueryData(departmentKey(before, 'chats'))).toBeUndefined();
    // The keys carry the active department, so B's data can never be A's.
    expect(departmentKey(makeIdentity({ active_department: B }), 'documents')).not.toEqual(
      departmentKey(before, 'documents'),
    );
    // Identity-scoped data (the department list) stays.
    expect(client.getQueryData(['identity', before.user_id, 'departments'])).toHaveLength(3);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
