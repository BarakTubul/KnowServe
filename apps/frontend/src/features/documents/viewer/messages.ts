import { DEFAULT_LANGUAGE, messageForCode, type Language } from '@/lib/i18n/languages';

/**
 * Viewer message catalogs (FE-ARCH-14, PROD-13, Q13/OPEN-29): one per language, errors keyed by stable
 * API error code with a generic fallback. Components never render `error.message`. The not-available
 * text is one neutral pair, identical for every cause (SEC-02).
 */
export interface ViewerCatalog {
  documentsLink: string;
  backToDocuments: string;
  loadingDocument: string;
  loadingViewer: string;
  toolbarLabel: string;
  previous: string;
  previousLabel: string;
  next: string;
  nextLabel: string;
  zoomOutLabel: string;
  zoomInLabel: string;
  pageOf: (page: number, total: number) => string;
  pageMissing: (page: number) => string;
  notAvailableTitle: string;
  notAvailableBody: string;
  errors: Record<string, string> & { generic: string };
}

const en: ViewerCatalog = {
  documentsLink: 'Documents',
  backToDocuments: 'Back to documents',
  loadingDocument: 'Loading document…',
  loadingViewer: 'Loading viewer…',
  toolbarLabel: 'PDF viewer',
  previous: 'Previous',
  previousLabel: 'Previous page',
  next: 'Next',
  nextLabel: 'Next page',
  zoomOutLabel: 'Zoom out',
  zoomInLabel: 'Zoom in',
  pageOf: (page, total) => `Page ${page} of ${total}`,
  pageMissing: (page) => `That page does not exist in this document. Showing page ${page} instead.`,
  notAvailableTitle: 'Document not found or not available',
  notAvailableBody:
    'This document does not exist or you do not have access to it in the current department.',
  errors: {
    generic: 'Something went wrong while opening this document. Please try again.',
    NETWORK_ERROR: 'We could not reach KnowServe. Check your connection and try again.',
    RATE_LIMITED: 'You are going a little fast. Wait a moment and try again.',
    QUOTA_EXCEEDED: 'The demo has reached its usage limit for now. Please try again later.',
    SERVICE_UNAVAILABLE: 'KnowServe is temporarily unavailable. Please try again in a moment.',
    UPSTREAM_UNAVAILABLE: 'KnowServe is temporarily unavailable. Please try again in a moment.',
    UNAUTHENTICATED: 'Your session ended. Sign in again to continue.',
    ACTIVE_DEPARTMENT_REQUIRED: 'Choose a department to see documents.',
    PDF_UNREADABLE: 'This document could not be displayed.',
  },
};

const he: ViewerCatalog = {
  documentsLink: 'מסמכים',
  backToDocuments: 'חזרה למסמכים',
  loadingDocument: 'טוענים את המסמך…',
  loadingViewer: 'טוענים את הצופה…',
  toolbarLabel: 'כלי צפייה במסמך',
  previous: 'הקודם',
  previousLabel: 'העמוד הקודם',
  next: 'הבא',
  nextLabel: 'העמוד הבא',
  zoomOutLabel: 'הקטנה',
  zoomInLabel: 'הגדלה',
  pageOf: (page, total) => `עמוד ${page} מתוך ${total}`,
  pageMissing: (page) => `העמוד הזה לא קיים במסמך. מוצג עמוד ${page} במקומו.`,
  notAvailableTitle: 'המסמך לא נמצא או שאינו זמין',
  notAvailableBody: 'המסמך לא קיים, או שאין לכם גישה אליו במחלקה הנוכחית.',
  errors: {
    generic: 'משהו השתבש בפתיחת המסמך. אפשר לנסות שוב.',
    NETWORK_ERROR: 'לא הצלחנו להתחבר. כדאי לבדוק את החיבור לאינטרנט ולנסות שוב.',
    RATE_LIMITED: 'הפעולות מהירות מדי. אפשר להמתין רגע ולנסות שוב.',
    QUOTA_EXCEEDED: 'ההדגמה הגיעה כרגע למגבלת השימוש. אפשר לנסות שוב מאוחר יותר.',
    SERVICE_UNAVAILABLE: 'השירות אינו זמין כרגע. אפשר לנסות שוב בעוד רגע.',
    UPSTREAM_UNAVAILABLE: 'השירות אינו זמין כרגע. אפשר לנסות שוב בעוד רגע.',
    UNAUTHENTICATED: 'החיבור שלכם הסתיים. יש להתחבר שוב כדי להמשיך.',
    ACTIVE_DEPARTMENT_REQUIRED: 'בחרו מחלקה כדי לראות מסמכים.',
    PDF_UNREADABLE: 'אי אפשר להציג את המסמך הזה.',
  },
};

export const VIEWER_CATALOGS: Record<Language, ViewerCatalog> = { en, he };

export function viewerCatalog(language: string = DEFAULT_LANGUAGE): ViewerCatalog {
  return Object.hasOwn(VIEWER_CATALOGS, language) ? VIEWER_CATALOGS[language as Language] : en;
}

export function viewerMessage(code: string, catalog: ViewerCatalog = en): string {
  return messageForCode(catalog.errors, en.errors, code);
}
