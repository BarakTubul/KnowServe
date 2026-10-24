import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AppRoutes } from './routes';

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('m0_ac02 status page', () => {
  it('prod_01_demo_mode_badge_is_present', async () => {
    vi.stubGlobal('fetch', () => new Promise(() => {}));
    renderAt('/');
    expect(screen.getByTestId('demo-mode-badge')).toHaveTextContent('Demo Mode');
  });

  it('m0_ac02_renders_loading_state', () => {
    vi.stubGlobal('fetch', () => new Promise(() => {}));
    renderAt('/');
    expect(screen.getByTestId('api-loading')).toBeInTheDocument();
  });

  it('m0_ac02_renders_success_state', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve(
        new Response(
          JSON.stringify({ service: 'api', version: '1.2.3', environment: 'ci', database: 'ok' }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
      ),
    );
    renderAt('/');
    expect(await screen.findByTestId('api-status')).toBeInTheDocument();
    expect(screen.getByTestId('api-service')).toHaveTextContent('api');
    expect(screen.getByTestId('api-version')).toHaveTextContent('1.2.3');
    expect(screen.getByTestId('api-environment')).toHaveTextContent('ci');
    expect(screen.getByTestId('api-database')).toHaveTextContent('ok');
  });

  it('fe_arch_03_renders_error_state_with_code_and_request_id', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            error: {
              code: 'DEPENDENCY_UNAVAILABLE',
              message: 'down',
              request_id: 'req_0123456789abcdef',
            },
          }),
          { status: 503, headers: { 'content-type': 'application/json' } },
        ),
      ),
    );
    renderAt('/');
    expect(await screen.findByTestId('api-error')).toBeInTheDocument();
    expect(screen.getByTestId('api-error-code')).toHaveTextContent('DEPENDENCY_UNAVAILABLE');
    expect(screen.getByTestId('api-error-request-id')).toHaveTextContent('req_0123456789abcdef');
  });
});

describe('fe_arch_05 routing', () => {
  it('fe_arch_05_unknown_route_renders_not_found', () => {
    renderAt('/nope');
    expect(screen.getByTestId('not-found-page')).toBeInTheDocument();
    expect(screen.queryByTestId('status-page')).not.toBeInTheDocument();
  });
});
