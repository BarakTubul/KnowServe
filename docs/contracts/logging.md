# Logging contract (M0)

Requirements: ARCH-09, MON-03, MON-05, INFRA-09.

- One JSON object per line on stdout (Google Cloud Logging reads it). Configure with `knowserve_core.logging.configure_logging(service, level)`. No `print`.
- Fields always present: `timestamp` (ISO 8601 UTC), `severity`, `service` (`api` or `worker`), `logger`, `message`, `request_id`, `correlation_id`. Extra fields passed with `extra={...}` are added (for example `job_id`, `outbox_id`, `result`).
- Redaction: any field whose name contains `password`, `secret`, `token`, `authorization`, `cookie`, `api_key`, `signing_key`, `otp`, `csrf`, `signature` or `session` is replaced by `[REDACTED]`, and `Bearer …` values in messages are masked. Do not log request bodies, document content or chat content.
- Correlation: `request_id` is per request (`X-Request-ID`). `correlation_id` follows work across services: set from the request at enqueue time, stored on `jobs`/`outbox`, and restored by the Worker from the job row.
- Uvicorn's access log is disabled; request logging is the application's job when needed.
