import type { AdminDocument, DocumentStatus } from './admin-api';

/**
 * Interface text of the Admin screens. They are English only in M3 (OPEN-31 D8); every error text is in
 * `admin-error-messages.ts`, which has both languages.
 */
export const adminText = {
  title: 'Manage documents',
  backToDashboard: 'Back to dashboard',
  notAvailableTitle: 'Not available',
  notAvailableBody: 'This page is not available for your account.',
  searchLabel: 'Search by title',
  searchPlaceholder: 'Title or file name',
  statusFilterLabel: 'Status',
  allStatuses: 'All statuses',
  loading: 'Loading documents...',
  empty: 'There are no documents yet.',
  noMatch: 'No documents match your search.',
  retryLoad: 'Try again',
  loadMore: 'Load more',
  loadingMore: 'Loading...',
  owner: 'Owner',
  allowed: 'Can be read by',
  noAllowed: 'No department',
  pages: (count: number) => `${count} page${count === 1 ? '' : 's'}`,
  size: (bytes: number) =>
    bytes >= 1024 * 1024
      ? `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
      : `${Math.ceil(bytes / 1024)} KiB`,
  streamDegraded: 'Live updates are unavailable. This list refreshes on its own.',
  actions: {
    editAccess: 'Edit access',
    retry: 'Retry',
    retrying: 'Retrying...',
    replaceFile: 'Replace file',
    delete: 'Delete',
  },
  access: {
    title: 'Edit access',
    description: 'Choose which departments can read this document.',
    noReprocessing: 'Changing access does not reprocess the document.',
    atLeastOne: 'Choose at least one department.',
    save: 'Save',
    saving: 'Saving...',
    cancel: 'Cancel',
    loadingDepartments: 'Loading departments...',
  },
  remove: {
    title: 'Delete document',
    body: (title: string) =>
      `Delete "${title}"? It disappears from every department's library. This cannot be undone from here.`,
    confirm: 'Delete',
    deleting: 'Deleting...',
    cancel: 'Cancel',
  },
} as const;

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  queued: 'Queued',
  processing: 'Processing',
  ready: 'Ready',
  failed: 'Failed',
};

export const PHASE_LABEL: Record<NonNullable<AdminDocument['phase']>, string> = {
  fetching: 'Fetching the file',
  extracting: 'Extracting text',
  chunking: 'Splitting the text',
  embedding: 'Preparing for search',
  publishing: 'Publishing',
};

/** What the derived job state means for the Admin. Only states that need attention have a text. */
export const DELIVERY_HINT: Partial<Record<NonNullable<AdminDocument['delivery_state']>, string>> =
  {
    publish_failed: 'The processing request could not be sent. Retry to send it again.',
    unpublished_stuck:
      'The processing request has not been sent for a long time. Retry to send it again.',
    queued_stuck: 'This document has waited in the queue for a long time.',
    processing_stuck: 'Processing is taking longer than expected.',
  };
