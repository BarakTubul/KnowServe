/**
 * Friendly, non-technical viewer messages keyed by stable API error code (FE-ARCH-14, PROD-13).
 * Q13 (OPEN-29) is open: this is the recommended default (English, one catalog keyed by code with a
 * generic fallback). When the product-wide catalog lands, this file moves into it unchanged.
 * Components never render `error.message`.
 */
const MESSAGES: Record<string, string> = {
  NETWORK_ERROR: 'We could not reach KnowServe. Check your connection and try again.',
  RATE_LIMITED: 'You are going a little fast. Wait a moment and try again.',
  QUOTA_EXCEEDED: 'The demo has reached its usage limit for now. Please try again later.',
  SERVICE_UNAVAILABLE: 'KnowServe is temporarily unavailable. Please try again in a moment.',
  UPSTREAM_UNAVAILABLE: 'KnowServe is temporarily unavailable. Please try again in a moment.',
  UNAUTHENTICATED: 'Your session ended. Sign in again to continue.',
  ACTIVE_DEPARTMENT_REQUIRED: 'Choose a department to see documents.',
  PDF_UNREADABLE: 'This document could not be displayed.',
};

export const GENERIC_MESSAGE =
  'Something went wrong while opening this document. Please try again.';

/** The one neutral not-found text, identical for every cause (SEC-02). */
export const NOT_AVAILABLE_TITLE = 'Document not found or not available';
export const NOT_AVAILABLE_BODY =
  'This document does not exist or you do not have access to it in the current department.';

export function viewerMessage(code: string): string {
  return MESSAGES[code] ?? GENERIC_MESSAGE;
}
