import { ApiError } from '@/lib/api/errors';
import { DEFAULT_LANGUAGE, messageForCode, type Language } from '@/lib/i18n/languages';

/**
 * Library message catalogs (PROD-13, FE-ARCH-14, Q13/OPEN-29): one per language, error messages keyed
 * by stable API error code with a generic fallback. Hebrew is written for plain, friendly reading.
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

const he: LibraryCatalog = {
  title: 'מסמכים',
  backToDashboard: 'חזרה ללוח הבקרה',
  changeDepartment: 'החלפת מחלקה',
  searchLabel: 'חיפוש מסמכים',
  searchPlaceholder: 'חיפוש לפי כותרת או שם קובץ',
  ownerFilterLabel: 'המחלקה שמחזיקה במסמך',
  allDepartments: 'כל המחלקות',
  loading: 'טוענים מסמכים…',
  empty: 'אין מסמכים זמינים במחלקה הזו.',
  noMatch: 'לא נמצאו מסמכים שמתאימים לחיפוש.',
  retry: 'לנסות שוב',
  loadMore: 'להציג עוד',
  loadingMore: 'טוענים…',
  ownerDepartment: (name) => `המחלקה שמחזיקה במסמך: ${name}`,
  pages: (count) => (count === 1 ? 'עמוד אחד' : `${count} עמודים`),
  errors: {
    generic: 'לא הצלחנו לטעון את המסמכים. אפשר לנסות שוב.',
    NETWORK_ERROR: 'לא הצלחנו להתחבר לשרת. כדאי לבדוק את החיבור לאינטרנט ולנסות שוב.',
    UNAUTHENTICATED: 'החיבור שלכם הסתיים. יש להתחבר שוב.',
    ACTIVE_DEPARTMENT_REQUIRED: 'בחרו מחלקה כדי לראות את המסמכים שלה.',
    RATE_LIMITED: 'יש כרגע יותר מדי בקשות. אפשר להמתין רגע ולנסות שוב.',
    UNAVAILABLE: 'השירות אינו זמין כרגע. אפשר לנסות שוב בעוד זמן קצר.',
    VALIDATION_ERROR: 'אי אפשר להשתמש בחיפוש הזה. כדאי לשנות אותו ולנסות שוב.',
  },
};

export const CATALOGS: Record<Language, LibraryCatalog> = { en, he };

export function libraryCatalog(language: string = DEFAULT_LANGUAGE): LibraryCatalog {
  return Object.hasOwn(CATALOGS, language) ? CATALOGS[language as Language] : en;
}

/** Friendly text for a failed list call: by error code, a generic fallback, never `error.message`. */
export function libraryErrorMessage(error: unknown, catalog: LibraryCatalog = en) {
  if (error instanceof ApiError) {
    let code = error.code;
    if (error.status === 503) code = 'UNAVAILABLE';
    else if (error.status === 429) code = 'RATE_LIMITED';
    else if (error.status === 422) code = 'VALIDATION_ERROR';
    return messageForCode(catalog.errors, en.errors, code);
  }
  return catalog.errors.generic;
}
