# Backend observability, audit and usage accounting

**Status:** Target spec (M0 logging foundation; M1 audit; M4 usage accounting). Not implemented: the legacy code uses `print` and has a placeholder `/monitor` route.

## Purpose
Structured logs, correlation ids, audit events, basic metrics and AI usage records. There is no Sentry or full distributed tracing (STACK-X).

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| MON-02 | AI usage is recorded per request: identity type, identity, department, model, tokens in/out, estimated cost, outcome (done/aborted/error) and latency. These records feed the quotas and the budget (COST-02, COST-03). | M4 |
| MON-03 | Both services log structured JSON to stdout/stderr, which goes to Google Cloud Logging. Every log line carries a request/correlation id, which is propagated from the API through the outbox and the job to the Worker phases. | M0 |
| MON-04 | Audit events are recorded for auth, admin and security actions: signup, verification, login success/failure (by method), Email OTP request and verification outcome, logout, admin document actions, permission changes, and rejected Worker signatures. | M1/M3 |
| MON-05 | Logs never contain passwords, OTP codes, CSRF or session tokens, cookies, API keys, or full document or chat content. | M0 |
| MON-06 | Basic Cloud Monitoring metrics and alerts cover error rate, job failures and stuck outbox rows, plus provider billing alerts (COST-04). | M0/M3 |

### Retired IDs (do not reuse)
| ID | Was | Reason |
|---|---|---|
| MON-01 | Admin-only `GET /monitor/` placeholder | No monitor page is in the target product. Observability is through Cloud Logging and Monitoring. |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| MON-02 | integration | A completed, an aborted and a failed chat | three usage rows with the correct outcome and token counts |
| MON-03 | integration | API request that enqueues a job processed by the Worker | the same correlation id appears in the API and Worker logs; lines parse as JSON |
| MON-04 | integration | Failed login; admin access change | audit entries exist |
| MON-05 | unit | Logging filter with a password, OTP code, cookie or token in the context | redacted |
| MON-06 | review | Alert policies in Terraform or in the documented manual steps | present |

## Current implementation (LEGACY, not migrated)
- `routers/monitor.py` returns a static placeholder. The `MonitorLog` and `ChatHistory` models are unused.
- Logging is `print` with emoji everywhere; `routers/auth.py` uses `logging`.
- `services/chat_service.py` and `agent/llama_tools.py` print tool outputs, which include document content (this contradicts MON-05).

## Known gaps
Every MON requirement is unimplemented.

## Related docs
`architecture.md`, `../architecture/infrastructure.md`, `chat.md`
