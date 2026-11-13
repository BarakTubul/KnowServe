/**
 * Limits shown as hints and checked before sending (OPEN-31 D1). They are the configured defaults of
 * the server; the server validates independently and its answer is what decides.
 */
export const PDF_MAX_BYTES = 20 * 1024 * 1024;
export const PDF_MAX_PAGES = 300;
export const ZIP_MAX_BYTES = 25 * 1024 * 1024;
export const ZIP_MAX_FILES = 20;
export const TITLE_MAX_LENGTH = 200;

/** Failure codes after which a retry cannot succeed (ING-23): the UI offers Replace file first. Presentation only. */
export const TERMINAL_FAILURES: ReadonlySet<string> = new Set([
  'NO_EXTRACTABLE_TEXT',
  'INVALID_PDF',
  'PDF_ENCRYPTED',
  'TOO_MANY_PAGES',
  'DOCUMENT_DELETED',
]);

/** Interface text of the upload, replace and import forms (English only in M3, D8). */
export const uploadText = {
  open: 'Upload a document',
  close: 'Close',
  formTitle: 'Upload a document',
  fileLabel: 'PDF file',
  fileHint: `PDF only, up to 20 MiB and ${PDF_MAX_PAGES} pages.`,
  titleLabel: 'Title',
  ownerLabel: 'Owner department',
  ownerPlaceholder: 'Choose a department',
  ownerNote: 'Ownership alone does not give a department access to the document.',
  allowedLegend: 'Departments that can read this document',
  allowedNote:
    'Choosing an owner pre-selects it here. You can change the selection before uploading.',
  submit: 'Upload',
  submitting: 'Uploading...',
  loadingDepartments: 'Loading departments...',
  uploaded: (title: string) => `"${title}" was uploaded and is queued for processing.`,
  replace: {
    title: 'Replace file',
    fileLabel: 'New PDF file',
    notice:
      'The document ID, owner and access stay the same. The document stays unavailable to users until the new file is processed successfully.',
    submit: 'Replace file',
    submitting: 'Replacing...',
    cancel: 'Cancel',
  },
  importer: {
    open: 'Import a ZIP',
    title: 'Import a ZIP of documents',
    hint: `A ZIP with a manifest.json and up to ${ZIP_MAX_FILES} PDFs, up to 25 MiB. Every entry must list the departments that can read it; nothing is inferred from the owner.`,
    fileLabel: 'ZIP file',
    preview: 'Preview',
    previewing: 'Checking...',
    summary: (valid: number, invalid: number) =>
      `${valid} valid, ${invalid} invalid. Nothing has been created yet.`,
    noDefault:
      'There is no default access for imports. Entries without departments are not imported.',
    valid: 'Valid',
    invalid: 'Invalid',
    owner: 'Owner',
    allowed: 'Can be read by',
    confirm: (count: number) => `Import ${count} valid document${count === 1 ? '' : 's'}`,
    confirming: 'Importing...',
    cancel: 'Start over',
    resultsTitle: 'Import results',
    created: 'Created',
    rejected: 'Not imported',
    resultSummary: (created: number, rejected: number) =>
      `${created} created, ${rejected} not imported.`,
    retryFailed: 'Retry the files that were not imported',
    retryNote: 'This sends the ZIP again as a new import.',
  },
} as const;
