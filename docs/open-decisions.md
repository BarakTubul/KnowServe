# Open decisions, review-required tensions and deferrals

Agents must not turn any item here into a binding choice. Each one is resolved by the user, or, where noted, by a measured decision recorded in an ADR during the milestone that needs it. When an item is resolved, update this file and the specs that reference it.

## Open (from the approved source package)
| ID | Question | Needed by | Notes |
|---|---|---|---|
| OPEN-01 | Shared Domain Core ownership: Owner-owned vs a dedicated Core Agent vs distributed authorship | M0 start | The user chose a *focused* shared core but has **not** chosen its ownership. Owner-owned is a recommendation only. |
| OPEN-02 | Final OpenAI-family chat model via OpenRouter | M4 | Chosen by a quality/cost benchmark. |
| OPEN-03 | Retrieval threshold, final `top_k`, chunk size/overlap | M4/M6 | 5 / 512 / 64 are initial baselines, not benchmarked values. |
| OPEN-04 | CSRF implementation; exact cookie site/domain topology (Pages ↔ Cloud Run) | M0 spike / M1 | Determines `SameSite` and CORS settings (AUTH-06, AUTH-19). |
| OPEN-05 | Quotas, concurrency, token caps, file size/count limits, demo session lifetime and purge cadence | M1/M3/M4 | COST-02, SEC-11, AUTH-16. |
| OPEN-06 | Terraform backend, provider/resource feasibility, actual costs/quotas, GCP regions, Secret Manager limits | M0 | INFRA-03. |
| OPEN-07 | Detailed M0 concurrency/integration sequencing; developer onboarding scripts | M0 | |
| OPEN-08 | Evaluation thresholds, sample counts, AI judge selection | M6 | Does not reopen the evaluation strategy. |
| OPEN-09 | Whether provider-native Postgres backup/restore is acceptable on the selected free tiers | M0 spike | INFRA-08. |

## Review-required tensions (from the source package)
| ID | Tension | Current documented position |
|---|---|---|
| OPEN-10 | $0–5/month including modest AI may not be achievable with independent managed services and real traffic | Verify in the M0 spike (COST-01); not guaranteed. |
| OPEN-11 | "Restricted immediately after revocation" vs text already streamed or persisted | The server stops in-flight streams and hides or redacts persisted history (SEC-09, CHAT-13, CHAT-15). Content already delivered to a client cannot be recalled. The exact redaction UX needs review. |
| — | Fast-path publish plus scheduled recovery is at-least-once | Documented as at-least-once with idempotency (ING-15); never claimed as exactly-once. Not open, kept here for visibility. |
| — | Docs-only reconciliation vs legacy code | Every spec has "Current implementation (LEGACY)" and "Known gaps" sections. Not open. |

## Ambiguities found during reconciliation (need user confirmation)
| ID | Question | Interim wording in specs |
|---|---|---|
| OPEN-12 | Can every user (registered or demo) select **any** seeded department, or is selection restricted per user? | The source says users "select/switch among seeded departments". Specs describe selection without per-user restriction, and authorization is always evaluated against the *active* department. |
| OPEN-13 | Does the Admin have an active department and/or read access to all documents in **user-facing** paths (library, viewer, chat)? | Specs give the Admin full access only to Admin APIs (ADM-*). In user-facing paths the Admin follows SEC-07 like any user until this is decided. Legacy DOC-02 ("admin sees all") is retired. |
| OPEN-14 | Exact API error contract beyond the 401/403/404 rules: the error body format, the code for a missing active department, and the duplicate-email response and enumeration posture | Fixed in the M1/M2 API contract. |
| OPEN-15 | Password policy (≥8 chars, a digit, an uppercase letter) carried over from the legacy spec | Kept as AUTH-03 pending confirmation; the source package doesn't specify one. |
| OPEN-16 | "At least one allowed department" on upload, carried over from the legacy spec (ADM-05) | Kept pending confirmation; it doesn't conflict with the source. |
| OPEN-17 | Handling of PDFs with no extractable text (no OCR in the MVP) | Treated as an ingestion failure with a reason (ING-09) until decided. |
| OPEN-18 | When and how to migrate `backend/` and `frontend/` to the proposed `apps/` and `packages/` layout | Future migration proposal for M0 planning; nothing is moved in this phase. |

## Deferred by explicit user instruction
| ID | Item |
|---|---|
| DEF-01 | Design of a varied, realistic fictional KnowServe document corpus. Do not expand it in this phase. |
| DEF-02 | Google OAuth, OCR, a custom model chooser, full tracing/Sentry, hybrid retrieval/reranker, standalone antivirus, a large admin system. None are MVP features. |
