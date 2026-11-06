import { ApiError } from '@/lib/api/errors';
import { AuthFlowError } from './gateway-types';

export const MIN_PASSWORD_LENGTH = 8;

export const GENERIC_SIGN_IN_ERROR = 'The email or password is not correct.';
export const SIGN_UP_NEUTRAL_MESSAGE =
  'We could not create an account with this email. If you already have an account, sign in or reset your password.';
export const RESET_CONFIRMATION =
  'If an account exists for this email, we sent a link to reset the password. Check your inbox.';

/** "Try again in 2 minutes." for a Retry-After value in seconds; a generic hint without one. */
export function retryText(seconds: number | undefined): string {
  if (seconds === undefined) return 'Try again later.';
  if (seconds < 60)
    return `Try again in ${Math.max(seconds, 1)} second${seconds === 1 ? '' : 's'}.`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `Try again in ${minutes} minute${minutes === 1 ? '' : 's'}.`;
  const hours = Math.ceil(minutes / 60);
  return `Try again in ${hours} hour${hours === 1 ? '' : 's'}.`;
}

/** User-facing text for a failed API call. Never includes tokens or internal detail. */
export function describeApiError(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Something went wrong. Try again.';
  switch (error.code) {
    case 'RATE_LIMITED':
      return `Too many requests. ${retryText(error.retryAfterSeconds)}`;
    case 'QUOTA_EXCEEDED':
      return `You have reached today's usage limit. ${retryText(error.retryAfterSeconds)}`;
    case 'AI_UNAVAILABLE':
      return 'The AI assistant is temporarily unavailable. You can still browse your documents.';
    case 'NETWORK_ERROR':
      return 'Could not reach the server. Check your connection and try again.';
    case 'REAUTH_REQUIRED':
      return 'Your sign-in is still too old. Sign in again with your password or Google.';
    case 'EMAIL_NOT_VERIFIED':
      return 'Verify your email address first.';
    case 'UNAUTHENTICATED':
      return 'Sign-in failed. Try again.';
    default:
      return error.requestId
        ? `Something went wrong (reference ${error.requestId}).`
        : 'Something went wrong. Try again.';
  }
}

/** Text for any failure in a sign-in, sign-up or linking step (Firebase or API). */
export function describeFlowError(error: unknown): string {
  if (error instanceof AuthFlowError) {
    switch (error.kind) {
      case 'invalid-credential':
        return GENERIC_SIGN_IN_ERROR;
      case 'weak-password':
        return 'This password does not meet the password policy. Choose a longer one.';
      case 'popup-cancelled':
        return 'The Google window was closed before finishing. Try again.';
      case 'popup-blocked':
        return 'Your browser blocked the Google window. Allow pop-ups for this site and try again.';
      case 'too-many-requests':
        return 'Too many attempts. Wait a few minutes and try again.';
      case 'network':
        return 'Could not reach the sign-in service. Check your connection and try again.';
      case 'requires-recent-login':
        return 'For security, confirm it is you again to continue.';
      default:
        return 'Something went wrong. Try again.';
    }
  }
  return describeApiError(error);
}

/** Password rule of FE-AUTH-03: only a minimum length, counted in characters; Unicode is welcome. */
export function isPasswordLongEnough(password: string): boolean {
  return Array.from(password).length >= MIN_PASSWORD_LENGTH;
}
