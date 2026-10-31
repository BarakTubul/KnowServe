# Authentication, authorization, isolation and security

## Authentication decisions
- FastAPI **focused Auth Module**, not all-in-one authentication framework.
- Password hashing with `pwdlib` Argon2id. Email/password signup with mandatory email verification; verification email via Resend.
- Opaque random server-side session IDs; only a **hash of token** saved in PostgreSQL; browser stores token in `Secure`, `HttpOnly`, appropriately scoped `SameSite` cookie; session expiration, rotation against fixation, logout revocation.
- CSRF protection for cookie-authenticated mutations, bounded login attempts and per-client/user rate limits. Use browser cookie and CORS/origin policy compatible with actual Pages/Cloud Run domains.
- `Try Demo`: isolated, temporary anonymous visitor session/identity, separate from registered accounts, expires and is purged.
- No JWT as primary session scheme. Do not confuse Starlette signed-cookie `SessionMiddleware` with opaque DB-backed sessions.

## Permission model and API responses
- `owner_department_id` on documents identifies the owning department, **never implies read access**.
- Explicit join rows `document_department_access` determine readable departments. Organization-wide docs are represented by rows for all authorized departments, without a special access scope.
- Every route returning PDF bytes, metadata, previews, citations, RAG chunks or chat history must independently enforce server-side user/session/department/document permissions.
- Department switch resets/bounds frontend data and multi-turn context to the active department; cached data is partitioned by identity/department, and invalidated on logout, switch, revocation.
- Anonymous unauthenticated request to protected resource => `401`; authenticated request for forbidden **or unknown document** => indistinguishable `404`; non-Admin accessing an Admin-only API => `403`.
- Retrieval uses only active, current, ready, authorized documents with access constraints applied in SQL **before Top-K**; do not retrieve globally and filter later.
- Revoked or soft-deleted docs must immediately cease being accessible via direct PDF, library, retrieval, citation links and historical chat display (redact/hide sensitive text if needed); streaming output must stop/revalidate on revocation.

## Defense in depth
- PDFs and ZIP files are untrusted: validate file signatures/types, filenames/paths, archive traversal/symlinks, zip bombs, count/size limits; bounded sandboxed resource/time processing. OCR and separate antivirus system are not in MVP.
- Documents/prompts are lower-trust than system/developer instructions. Model has no administrative tool access. Treat prompt-injection attempts as adversarial tests, not trusted instructions.
- Secrets in Google Secret Manager, local `.env` excluded from Git; Terraform manages infrastructure/permissions, **never secret values in Terraform state**. Github OIDC to GCP. Per-service least privilege (API/worker).
- Auth/admin/security audit logs, request/correlation IDs; avoid passwords, cookies, keys, full document/chat content in logs.
- Rate limits, distinct anonymous/registered AI quotas, token caps, concurrency limits, global budget reservation, spend kill-switch and hard failure closed for DB/auth issues.

## Required acceptance scenarios
- Direct URL bypass to restricted PDF yields 404; owner department alone cannot read doc.
- Retrieval and citations never reveal other departments; active revision/ready filter holds.
- Session fixation, CSRF, verification bypass, privilege escalation, revoked session and Demo cross-user/cross-department isolation tests.
- A changed document permission invalidates applicable cached/history/streamed disclosure immediately.
