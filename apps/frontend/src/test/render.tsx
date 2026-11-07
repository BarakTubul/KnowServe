import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { AppRoutes } from '@/app/routes';
import { ApiNoticeBanner } from '@/features/auth/api-notice-banner';
import { AuthProvider } from '@/features/auth/auth-provider';
import { LanguageProvider } from '@/lib/i18n/language-provider';
import { createFakeGateway, type FakeGateway } from './fake-gateway';

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}</output>;
}

/** Renders the whole app (router, provider, banner) with a fake Firebase gateway and a fresh cache. */
export function renderApp(path: string, gateway: FakeGateway = createFakeGateway()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();
  const view = render(
    <QueryClientProvider client={client}>
      <LanguageProvider>
        <MemoryRouter initialEntries={[path]}>
          <AuthProvider gateway={gateway}>
            <ApiNoticeBanner />
            <AppRoutes />
            <LocationProbe />
          </AuthProvider>
        </MemoryRouter>
      </LanguageProvider>
    </QueryClientProvider>,
  );
  return { ...view, client, gateway, user };
}
