import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from '@/features/auth/auth-provider';
import { ApiNoticeBanner } from '@/features/auth/api-notice-banner';
import { LanguageProvider } from '@/lib/i18n/language-provider';
import { AppRoutes } from './routes';

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <LanguageProvider>
        <BrowserRouter>
          <AuthProvider>
            <ApiNoticeBanner />
            <AppRoutes />
          </AuthProvider>
        </BrowserRouter>
      </LanguageProvider>
    </QueryClientProvider>
  );
}
