import { Route, Routes } from 'react-router-dom';
import { NotFoundPage } from '@/features/status/not-found-page';
import { StatusPage } from '@/features/status/status-page';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<StatusPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
