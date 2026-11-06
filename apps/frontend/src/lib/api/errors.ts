/** Typed API error parsed from the standard envelope {error:{code,message,request_id}} (FE-ARCH-03). */
export class ApiError extends Error {
  readonly code: string;
  readonly requestId: string | undefined;
  readonly status: number;
  /** Seconds from a Retry-After header (429/503), when the API sent one. */
  readonly retryAfterSeconds: number | undefined;

  constructor(params: {
    code: string;
    message: string;
    requestId?: string | undefined;
    status: number;
    retryAfterSeconds?: number | undefined;
  }) {
    super(params.message);
    this.name = 'ApiError';
    this.code = params.code;
    this.requestId = params.requestId;
    this.status = params.status;
    this.retryAfterSeconds = params.retryAfterSeconds;
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

/** Build an ApiError from a non-2xx response body; falls back to generic codes if not an envelope. */
export function parseApiError(
  status: number,
  body: unknown,
  headerRequestId?: string | null,
  retryAfter?: string | null,
): ApiError {
  const retryAfterSeconds = parseRetryAfter(retryAfter);
  const err = isRecord(body) ? body['error'] : undefined;
  if (isRecord(err) && typeof err['code'] === 'string' && typeof err['message'] === 'string') {
    const rid = typeof err['request_id'] === 'string' ? err['request_id'] : headerRequestId;
    return new ApiError({
      code: err['code'],
      message: err['message'],
      requestId: rid ?? undefined,
      status,
      retryAfterSeconds,
    });
  }
  return new ApiError({
    code: 'UNEXPECTED_RESPONSE',
    message: `Unexpected response (HTTP ${status})`,
    requestId: headerRequestId ?? undefined,
    status,
    retryAfterSeconds,
  });
}

/** Retry-After in delta-seconds form (the API sends seconds); anything else is ignored. */
function parseRetryAfter(value: string | null | undefined): number | undefined {
  if (!value || !/^\d+$/.test(value.trim())) return undefined;
  return Number.parseInt(value, 10);
}
