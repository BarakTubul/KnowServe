# ADR 0009: M3 Admin API, idempotency and ZIP import

Status: accepted by the Owner on 2026-11-13 (OPEN-31 D1, D8, D10, D12, D14), contract implemented in M3-01.

## Context
The Admin uploads PDFs and ZIPs. Double clicks, retries and a ZIP preview that stores nothing need one
consistent model.

## Decisions
- **Routes and models** are fixed in `docs/contracts/admin-api.md`; M3-01 shipped them as 501 stubs (implemented by M3-03 to M3-05b) so
  the OpenAPI snapshot and the generated TypeScript types exist before any slice starts.
- **Multipart through the API.** Browser, Pages proxy, Cloud Run API, R2. No presigned upload (D12).
- **Idempotency.** `Idempotency-Key` is required on create, replace and import confirmation, scoped to
  the Admin and the operation. A completed result is stored in `admin_idempotency_keys` in the same
  transaction as the rows it created. The same key with a different request is 409. Per-entry results
  of a ZIP confirmation are kept in `import_batch_entries`, so a confirmation that stopped half way
  resumes without creating an entry twice. A ZIP confirmation commits per entry, and the key row is
  finished after the last entry. Retrying a partly imported ZIP with a new key would create the
  finished entries again, so the Admin imports a ZIP of only the failed files instead.
- **ZIP preview creates nothing**, so confirmation receives the ZIP again and validates it again.
- **Manifest** names departments by slug, validated against the departments table. `allowed_departments`
  is required and non-empty. Nothing is inferred from the owner (D10).
- **Status codes.** Upload and replace answer 202 (processing continues in the Worker). A partial ZIP
  import is 200 with per-file results.
- **Stop switch.** `KS_UPLOADS_ENABLED=false` makes the upload-producing routes answer 503
  `UPLOADS_DISABLED`; everything else keeps working and running jobs continue (D14).
- **Errors.** Stable codes with a friendly English fallback in the backend and English and Hebrew
  frontend catalogs typed on the generated enum (D8).

## Consequences
The ZIP crosses the network twice. The 202 replaces the 200 that `admin-docs.md` listed for ADM-03.
