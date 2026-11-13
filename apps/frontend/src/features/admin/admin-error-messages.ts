import { ApiError } from '@/lib/api/errors';
import type { components } from '@/lib/api/schema';
import { DEFAULT_LANGUAGE, messageForCode, type Language } from '@/lib/i18n/languages';

/**
 * Error catalogs for the Admin upload and ingestion routes (PROD-13, FE-ARCH-14, OPEN-31 D8).
 *
 * The Admin screens are English only in M3, but every new user-facing error exists in English and
 * Hebrew. Both maps are typed on the generated API enums, so adding a code to the backend breaks
 * the build until both languages have a message for it.
 */
export type AdminErrorCode = components['schemas']['AdminErrorCode'];
export type FailureCode = components['schemas']['FailureCode'];

/**
 * Codes every authenticated route can return (docs/contracts/api.md, plus the transport failure the
 * client invents). They live in the same catalog so an Admin screen needs only one lookup (M3-06a).
 */
export type CommonCode =
  'NETWORK_ERROR' | 'FORBIDDEN' | 'VALIDATION_ERROR' | 'RATE_LIMITED' | 'DEPENDENCY_UNAVAILABLE';

type Generic = { generic: string };
type AdminCatalog = Record<AdminErrorCode | CommonCode, string> & Generic;

const adminEn: AdminCatalog = {
  generic: 'Something went wrong. Please try again.',
  NETWORK_ERROR: 'Could not reach the server. Check your connection and try again.',
  FORBIDDEN: 'This account is not allowed to manage documents.',
  VALIDATION_ERROR: 'Some of the entered values cannot be used. Check them and try again.',
  RATE_LIMITED: 'Too many requests right now. Wait a moment and try again.',
  DEPENDENCY_UNAVAILABLE: 'The service is temporarily unavailable. Try again in a few minutes.',
  DOCUMENT_NOT_FOUND: 'This document was not found. It may have been deleted.',
  FILE_EMPTY: 'The file is empty. Choose a file with content.',
  FILE_TOO_LARGE: 'The file is larger than the allowed size. Choose a smaller file.',
  NOT_A_PDF: 'Only PDF files can be uploaded.',
  INVALID_FILENAME: 'The file name is not allowed. Rename the file and try again.',
  TITLE_INVALID: 'Enter a title of 1 to 200 characters.',
  UNKNOWN_DEPARTMENT: 'One of the departments does not exist. Choose the departments again.',
  ALLOWED_DEPARTMENTS_MISSING: 'Choose which departments can read this document.',
  ALLOWED_DEPARTMENTS_EMPTY: 'Choose at least one department that can read this document.',
  ZIP_INVALID: 'This is not a valid ZIP file.',
  ZIP_TOO_LARGE: 'The ZIP file is larger than the allowed size.',
  ZIP_TOO_MANY_FILES: 'The ZIP file contains more documents than the limit.',
  ZIP_UNSAFE_PATH: 'A file path inside the ZIP is not allowed.',
  ZIP_SYMLINK: 'The ZIP file contains links, which are not allowed.',
  ZIP_RATIO_EXCEEDED: 'A file in the ZIP expands too much when unpacked.',
  ZIP_UNCOMPRESSED_TOO_LARGE: 'The ZIP file is too large when unpacked.',
  ZIP_NESTED_ARCHIVE: 'ZIP files inside the ZIP are not allowed.',
  ZIP_ENCRYPTED: 'The ZIP file is password protected. Remove the password and try again.',
  ZIP_DUPLICATE_NAME: 'Two files in the ZIP have the same name.',
  ZIP_UNLISTED_FILE: 'A file in the ZIP is not listed in the manifest.',
  MANIFEST_MISSING: 'The ZIP file has no manifest.json.',
  MANIFEST_INVALID: 'The manifest could not be read. Check its format.',
  MANIFEST_VERSION_UNSUPPORTED: 'This manifest version is not supported.',
  MANIFEST_TOO_LARGE: 'The manifest is too large.',
  MANIFEST_FILE_MISSING: 'The manifest lists a file that is not in the ZIP.',
  DOCUMENT_NOT_REPLACEABLE: 'Only a document that failed to process can have its file replaced.',
  DOCUMENT_NOT_RETRYABLE: 'This document cannot be retried right now.',
  IDEMPOTENCY_KEY_REUSED: 'This request was already used with different content. Start again.',
  UPLOAD_BACKLOG_FULL: 'Too many documents are being processed. Try again in a few minutes.',
  DAILY_UPLOAD_LIMIT: 'The daily upload limit has been reached. Try again tomorrow.',
  UPLOADS_DISABLED: 'Uploads are paused for now. You can still manage existing documents.',
};

const adminHe: AdminCatalog = {
  generic: 'משהו השתבש. כדאי לנסות שוב.',
  NETWORK_ERROR: 'לא הצלחנו להתחבר לשרת. כדאי לבדוק את החיבור לאינטרנט ולנסות שוב.',
  FORBIDDEN: 'לחשבון הזה אין הרשאה לנהל מסמכים.',
  VALIDATION_ERROR: 'אי אפשר להשתמש בחלק מהערכים שהוזנו. כדאי לבדוק אותם ולנסות שוב.',
  RATE_LIMITED: 'יש כרגע יותר מדי בקשות. אפשר להמתין רגע ולנסות שוב.',
  DEPENDENCY_UNAVAILABLE: 'השירות אינו זמין כרגע. אפשר לנסות שוב בעוד כמה דקות.',
  DOCUMENT_NOT_FOUND: 'המסמך לא נמצא. ייתכן שהוא נמחק.',
  FILE_EMPTY: 'הקובץ ריק. יש לבחור קובץ עם תוכן.',
  FILE_TOO_LARGE: 'הקובץ גדול מהגודל המותר. יש לבחור קובץ קטן יותר.',
  NOT_A_PDF: 'אפשר להעלות רק קבצי PDF.',
  INVALID_FILENAME: 'שם הקובץ לא מותר. יש לשנות את השם ולנסות שוב.',
  TITLE_INVALID: 'יש להזין כותרת באורך של 1 עד 200 תווים.',
  UNKNOWN_DEPARTMENT: 'אחת המחלקות לא קיימת. יש לבחור את המחלקות מחדש.',
  ALLOWED_DEPARTMENTS_MISSING: 'יש לבחור אילו מחלקות יכולות לקרוא את המסמך.',
  ALLOWED_DEPARTMENTS_EMPTY: 'יש לבחור לפחות מחלקה אחת שיכולה לקרוא את המסמך.',
  ZIP_INVALID: 'זה לא קובץ ZIP תקין.',
  ZIP_TOO_LARGE: 'קובץ ה-ZIP גדול מהגודל המותר.',
  ZIP_TOO_MANY_FILES: 'בקובץ ה-ZIP יש יותר מסמכים מהמותר.',
  ZIP_UNSAFE_PATH: 'נתיב של קובץ בתוך ה-ZIP אינו מותר.',
  ZIP_SYMLINK: 'בקובץ ה-ZIP יש קישורים, והם אינם מותרים.',
  ZIP_RATIO_EXCEEDED: 'אחד הקבצים ב-ZIP תופח יותר מדי כשפותחים אותו.',
  ZIP_UNCOMPRESSED_TOO_LARGE: 'קובץ ה-ZIP גדול מדי אחרי הפתיחה.',
  ZIP_NESTED_ARCHIVE: 'אי אפשר לכלול קבצי ZIP בתוך קובץ ZIP.',
  ZIP_ENCRYPTED: 'קובץ ה-ZIP מוגן בסיסמה. יש להסיר את הסיסמה ולנסות שוב.',
  ZIP_DUPLICATE_NAME: 'לשני קבצים ב-ZIP יש אותו שם.',
  ZIP_UNLISTED_FILE: 'קובץ ב-ZIP לא מופיע ברשימה (manifest).',
  MANIFEST_MISSING: 'בקובץ ה-ZIP חסר הקובץ manifest.json.',
  MANIFEST_INVALID: 'לא ניתן לקרוא את רשימת הקבצים (manifest). יש לבדוק את המבנה שלה.',
  MANIFEST_VERSION_UNSUPPORTED: 'גרסת רשימת הקבצים (manifest) אינה נתמכת.',
  MANIFEST_TOO_LARGE: 'רשימת הקבצים (manifest) גדולה מדי.',
  MANIFEST_FILE_MISSING: 'ברשימת הקבצים (manifest) מופיע קובץ שאינו בתוך ה-ZIP.',
  DOCUMENT_NOT_REPLACEABLE: 'אפשר להחליף קובץ רק במסמך שהעיבוד שלו נכשל.',
  DOCUMENT_NOT_RETRYABLE: 'אי אפשר לנסות שוב לעבד את המסמך הזה כרגע.',
  IDEMPOTENCY_KEY_REUSED: 'הבקשה הזו כבר שימשה עם תוכן אחר. יש להתחיל מחדש.',
  UPLOAD_BACKLOG_FULL: 'יותר מדי מסמכים בעיבוד כרגע. כדאי לנסות שוב בעוד כמה דקות.',
  DAILY_UPLOAD_LIMIT: 'הגעתם למגבלת ההעלאות היומית. אפשר לנסות שוב מחר.',
  UPLOADS_DISABLED: 'ההעלאות מושהות כרגע. עדיין אפשר לנהל מסמכים קיימים.',
};

const failureEn: Record<FailureCode, string> & Generic = {
  generic: 'Something went wrong while processing this document.',
  NO_EXTRACTABLE_TEXT:
    'No readable text was found in this PDF. It may be a scan or contain only images. Upload a version with selectable text.',
  INVALID_PDF: 'This file could not be opened as a PDF. Upload a different file.',
  PDF_ENCRYPTED: 'This PDF is password protected. Upload a version without a password.',
  TOO_MANY_PAGES: 'This PDF has more pages than the limit. Upload a shorter file.',
  DOCUMENT_DELETED: 'The document was deleted while it was being processed.',
  STORAGE_UNAVAILABLE: 'The file could not be read from storage. Try again in a few minutes.',
  EMBEDDING_FAILED: 'The text could not be prepared for search. Try again in a few minutes.',
  PROCESSING_TIMEOUT: 'Processing took too long. Try again, or upload a smaller file.',
  PROCESSING_CRASHED: 'Processing stopped unexpectedly. Try again, or upload a different file.',
  INTERNAL_ERROR: 'Something went wrong while processing this document. Try again.',
};

const failureHe: Record<FailureCode, string> & Generic = {
  generic: 'משהו השתבש בעיבוד המסמך.',
  NO_EXTRACTABLE_TEXT:
    'לא נמצא טקסט קריא ב-PDF הזה. ייתכן שזו סריקה או שיש בו רק תמונות. יש להעלות גרסה עם טקסט שאפשר לסמן.',
  INVALID_PDF: 'לא ניתן לפתוח את הקובץ כ-PDF. יש להעלות קובץ אחר.',
  PDF_ENCRYPTED: 'ה-PDF הזה מוגן בסיסמה. יש להעלות גרסה בלי סיסמה.',
  TOO_MANY_PAGES: 'ב-PDF הזה יש יותר עמודים מהמותר. יש להעלות קובץ קצר יותר.',
  DOCUMENT_DELETED: 'המסמך נמחק בזמן שהוא עובד.',
  STORAGE_UNAVAILABLE: 'לא ניתן היה לקרוא את הקובץ מהאחסון. כדאי לנסות שוב בעוד כמה דקות.',
  EMBEDDING_FAILED: 'לא ניתן היה להכין את הטקסט לחיפוש. כדאי לנסות שוב בעוד כמה דקות.',
  PROCESSING_TIMEOUT: 'העיבוד לקח יותר מדי זמן. אפשר לנסות שוב או להעלות קובץ קטן יותר.',
  PROCESSING_CRASHED: 'העיבוד נעצר באופן בלתי צפוי. אפשר לנסות שוב או להעלות קובץ אחר.',
  INTERNAL_ERROR: 'משהו השתבש בעיבוד המסמך. כדאי לנסות שוב.',
};

export const ADMIN_ERROR_CATALOGS = { en: adminEn, he: adminHe } as const;
export const FAILURE_CATALOGS = { en: failureEn, he: failureHe } as const;

/** Text for an Admin API error code in the given language. Unknown codes get the generic message. */
export function adminErrorMessage(code: string, language: Language = DEFAULT_LANGUAGE): string {
  return messageForCode(ADMIN_ERROR_CATALOGS[language], adminEn, code);
}

/** Text for a stored failure code. The server's English `failure_message` is never shown. */
export function failureMessage(code: string, language: Language = DEFAULT_LANGUAGE): string {
  return messageForCode(FAILURE_CATALOGS[language], failureEn, code);
}

/**
 * Text for any error an Admin call can raise (FE-ADM-09, FE-ARCH-14): the stable code selects the
 * catalog text and `error.message` is never shown. A 413 that the proxy answers without our envelope
 * still reads as "file too large" (M3 plan section 8).
 */
export function describeAdminError(error: unknown, language: Language = DEFAULT_LANGUAGE): string {
  if (!(error instanceof ApiError)) return adminErrorMessage('generic', language);
  if (error.code === 'UNEXPECTED_RESPONSE' && error.status === 413) {
    return adminErrorMessage('FILE_TOO_LARGE', language);
  }
  if (error.code === 'UNEXPECTED_RESPONSE' && error.status === 503) {
    return adminErrorMessage('DEPENDENCY_UNAVAILABLE', language);
  }
  return adminErrorMessage(error.code, language);
}
