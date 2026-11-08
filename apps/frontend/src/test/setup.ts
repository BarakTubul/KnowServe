import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { setCsrfToken } from '@/lib/api/csrf';

afterEach(() => {
  cleanup();
  if (typeof document !== 'undefined') {
    document.documentElement.lang = 'en';
    document.documentElement.removeAttribute('dir');
  }
  vi.unstubAllGlobals();
  setCsrfToken(null);
  // The Pages Function tests run in a node environment without web storage.
  if (typeof globalThis.sessionStorage !== 'undefined') globalThis.sessionStorage.clear();
  if (typeof globalThis.localStorage !== 'undefined') globalThis.localStorage.clear();
});
