import { ApiError } from '@/lib/api/errors';

/**
 * Minimal localized message catalog for the library (PROD-13, FE-ARCH-14).
 *
 * No i18n mechanism exists in the app yet and Q13/OPEN-29 (languages, selector, storage) is still open,
 * so this follows the recommended default: English, one catalog per language keyed by stable API error
 * code with a generic fallback, the language kept in the browser. More languages are added as entries
 * in `CATALOGS`; the owner names them. The M2-04b viewer can adopt or move this file.
 */
export interface LibraryCatalog {
  title: string;
  backToDashboard: string;
  changeDepartment: string;
  searchLabel: string;
  searchPlaceholder: string;
  ownerFilterLabel: string;
  allDepartments: string;
  loading: string;
  empty: string;
  noMatch: string;
  retry: string;
  loadMore: string;
  loadingMore: string;
  ownerDepartment: (name: string) => string;
  pages: (count: number) => string;
  errors: Record<string, string> & { generic: string };
}

const en: LibraryCatalog = {
  title: 'Documents',
  backToDashboard: 'Back to dashboard',
  changeDepartment: 'Change department',
  searchLabel: 'Search documents',
  searchPlaceholder: 'Search by title or file name',
  ownerFilterLabel: 'Owner department',
  allDepartments: 'All departments',
  loading: 'Loading documents...',
  empty: 'No documents are available in this department.',
  noMatch: 'No documents match your search.',
  retry: 'Try again',
  loadMore: 'Load more',
  loadingMore: 'Loading...',
  ownerDepartment: (name) => `Owner department: ${name}`,
  pages: (count) => `${count} page${count === 1 ? '' : 's'}`,
  errors: {
    generic: 'We could not load the documents. Please try again.',
    NETWORK_ERROR: 'We could not reach the server. Check your connection and try again.',
    UNAUTHENTICATED: 'Your session has ended. Please sign in again.',
    ACTIVE_DEPARTMENT_REQUIRED: 'Choose a department to see its documents.',
    RATE_LIMITED: 'Too many requests right now. Please wait a moment and try again.',
    UNAVAILABLE: 'The service is temporarily unavailable. Please try again soon.',
    VALIDATION_ERROR: 'That search could not be used. Change it and try again.',
  },
};

export const CATALOGS: Record<string, LibraryCatalog> = { en };
export const DEFAULT_LOCALE = 'en';
export const LOCALE_STORAGE_KEY = 'knowserve.locale';

/** The interface language kept in the browser; unknown or unreadable values fall back to English. */
export function currentLocale(): string {
  try {
    const stored = globalThis.localStorage?.getItem(LOCALE_STORAGE_KEY);
    if (stored && stored in CATALOGS) return stored;
  } catch {
    // Storage can be blocked; English is fine.
  }
  return DEFAULT_LOCALE;
}

export function libraryCatalog(locale: string = currentLocale()): LibraryCatalog {
  return CATALOGS[locale] ?? en;
}

/** Friendly text for a failed list call: by error code, a generic fallback, never `error.message`. */
export function libraryErrorMessage(error: unknown, catalog: LibraryCatalog = libraryCatalog()) {
  if (error instanceof ApiError) {
    let code = error.code;
    if (error.status === 503) code = 'UNAVAILABLE';
    else if (error.status === 429) code = 'RATE_LIMITED';
    else if (error.status === 422) code = 'VALIDATION_ERROR';
    const known = catalog.errors[code];
    if (known && code !== 'generic') return known;
  }
  return catalog.errors.generic;
}
