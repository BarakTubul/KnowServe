import { Route, Routes } from 'react-router-dom';
import { ActionPage } from '@/features/auth/action-page';
import { GuestOnly, RequireAuth } from '@/features/auth/guards';
import { LoginPage } from '@/features/auth/login-page';
import { DashboardPage } from '@/features/dashboard/dashboard-page';
import { LibraryPage } from '@/features/documents/library-page';
import { ViewerPage } from '@/features/documents/viewer-page';
import { NotFoundPage } from '@/features/status/not-found-page';
import { StatusPage } from '@/features/status/status-page';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<StatusPage />} />
      <Route path="/auth/action" element={<ActionPage />} />
      <Route element={<GuestOnly />}>
        <Route path="/login" element={<LoginPage />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/documents" element={<LibraryPage />} />
        <Route path="/documents/:id" element={<ViewerPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
