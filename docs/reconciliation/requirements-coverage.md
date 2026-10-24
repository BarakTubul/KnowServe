# Requirements coverage (reconciliation 2026-10-24)

Source: `../knowserve_requirements_handoff/knowserve_requirements_handoff/` (00–09, 90, 91). Precedence follows source 00: approved decisions > compatible repo specs > code (current state only).

States:
- **aligned**: the repo docs already matched the source and were kept.
- **updated**: the docs were rewritten or added to match the source.
- **open**: an undecided item, recorded and not resolved.

None of the target requirements is implemented (see `legacy-conflicts.md`).

## Source file → repo docs
| Source file | Topic | Repo docs (after) | State |
|---|---|---|---|
| 00_README | precedence, docs-only scope, outputs | `../README.md` (rules), this folder | updated |
| 01_PRODUCT_AND_UX | product, personas, routes, UI, constraints | `../cross-cutting/product-and-ux.md` (new), `../frontend/*.md` | updated |
| 02_AUTH_SECURITY_PERMISSIONS | sessions, CSRF, Argon2id, demo, ACL, 401/403/404, revocation, defense in depth | `../backend/auth.md`, `../cross-cutting/security-and-permissions.md` (new), `../frontend/auth.md` | updated |
| 03_DOCUMENTS_AND_INGESTION | R2, revisions, soft delete, ZIP, outbox, QStash, Worker, chunking, statuses | `../backend/admin-docs.md`, `../backend/ingestion.md`, `../backend/documents.md`, `../cross-cutting/document-lifecycle.md`, `../frontend/admin-upload.md` | updated |
| 04_RAG_CHAT_EVALUATION | LlamaIndex, OpenRouter, embeddings, authorized retriever, citations, SSE, history, evaluation | `../backend/chat.md`, `../frontend/chat.md`, `../cross-cutting/evaluation.md` (new) | updated; model and thresholds **open** (OPEN-02, OPEN-03, OPEN-08) |
| 05_TECH_STACK | stack table, exclusions, unselected details | `../architecture/tech-stack.md` (new), `../backend/architecture.md`, `../frontend/architecture.md` | updated |
| 06_INFRA_DEPLOYMENT_COST | envs, hosting, deploy, Terraform, secrets, logging, cost controls | `../architecture/infrastructure.md` (new), `../backend/monitoring.md` | updated; cost feasibility **open** (OPEN-10) |
| 07_AGENT_WORKFLOW | Owner, worktrees, scope control, review gates, handoffs, tests, milestones | `../workflow/agent-workflow.md` (new), `../workflow/testing.md` (new), `../../AGENTS.md`, `../../CLAUDE.md` | updated |
| 08_M0_FOUNDATION_PLAN | exit criteria, layout proposal, ownership, contracts, task graph, test plan | `../milestones/M0/plan.md` (new) | updated; shared core ownership **open** (OPEN-01) |
| 09_OPEN_DECISIONS | undecided, deferred, tensions | `../open-decisions.md` (new) | open (by nature) |
| 90_VALIDATION_CHECKLIST | acceptance checks | `validation-report.md` | updated |
| 91_REPO_DELTA_SNAPSHOT | initial mismatches | `legacy-conflicts.md` | updated |

## Required report table (from source 90)
| Requirement/topic | Original repo docs | Updated repo docs | State | Evidence/link | Remaining gap/code mismatch |
|---|---|---|---|---|---|
| Public fictional Demo Mode, identities, seeded departments, no public Admin signup | AGENTS.md (overview), backend/auth.md (roles, self-register) | product-and-ux PROD-01..05, auth AUTH-04, AUTH-16, AUTH-17, AUTH-20 | updated / **open** OPEN-12, OPEN-13 | `../cross-cutting/product-and-ux.md` | Legacy allows Admin self-registration; no demo; hard-coded departments |
| Opaque DB session hash, CSRF, Argon2id; no JWT target | backend/auth.md (JWT cookie/Bearer) | AUTH-06, AUTH-10, AUTH-14, AUTH-18 | updated / CSRF mechanism **open** OPEN-04 | `../backend/auth.md` | Legacy JWT + passlib |
| ACL: owner ≠ access, explicit rows, 401/403/404, department isolation | backend/documents.md (403 on forbidden, admin sees all) | SEC-01..10, DOC-05, DOC-07 | updated / Admin user-path access **open** OPEN-13 | `../cross-cutting/security-and-permissions.md` | Legacy 403s, no owner column |
| Private R2, React-PDF viewer, page deep links, no Drive/gdown | admin-docs ADM-06, ingestion ING-01, my-documents (download link) | DOC-04, DOC-09, FE-DOC-07..09, ADM-03, ADM-06 retired, ING-01 retired | updated | `../backend/documents.md`, `../frontend/my-documents.md` | Legacy gdown + local static PDFs |
| ZIP manifest/preview/confirm/partial retry; QStash signed Worker; outbox + recovery; at-least-once; leases; revisions; soft delete | ingestion.md (Celery/Redis), admin-docs.md | ADM-11..16, ING-12..22, LIFE-01..09 | updated | `../backend/ingestion.md`, `../backend/admin-docs.md` | None implemented |
| SSE (POST fetch + AbortController) chat; job status SSE from DB truth; no Redis pub/sub or WebSocket | chat.md (token/tool events), ingestion.md (WS) | CHAT-03, CHAT-12, ING-05, ING-07, ING-08 retired | updated | `../backend/chat.md` | Legacy WS + Redis pub/sub |
| LlamaIndex, OpenRouter chat, direct OpenAI embeddings, PyMuPDF4LLM, page-bounded SentenceSplitter, SQL-before-Top-K, threshold, citation checks | chat.md (agent tools, Chroma top_k 6) | CHAT-04, CHAT-11, CHAT-16, ING-02, ING-18, SEC-08 | updated / model and thresholds **open** OPEN-02, OPEN-03 | `../backend/chat.md` | Legacy FunctionAgent with gpt-4o-mini direct |
| Evaluation: human-verified golden set, security hard failures, progressive gates, reproducible reports | — (none) | EVAL-01..10 | updated (new) / thresholds **open** OPEN-08 | `../cross-cutting/evaluation.md` | None implemented; corpus deferred DEF-01 |
| Frontend: TS, Vite, Tailwind/shadcn, Router, TanStack Query, RHF/Zod, React-PDF, no Redux | frontend/architecture.md (JS, api.js, contexts) | FE-ARCH-01..13 | updated | `../frontend/architecture.md` | Legacy JS + npm + contexts |
| Infra: Pages/R2, Cloud Run API+Worker, Neon pgvector, Terraform, Secret Manager, OIDC, Docker/Compose, Cloud Logging | — (none) | INFRA-01..10, COST-01..05, MON-03..06 | updated (new) / feasibility **open** OPEN-06, OPEN-09, OPEN-10 | `../architecture/infrastructure.md` | None implemented; CORS lists Vercel |
| Tooling: uv/pnpm, Pyright/Ruff, ESLint/Prettier/strict TS, pytest/Vitest/Playwright | backend/architecture.md (unpinned requirements, pytest only) | STACK-30..36, ARCH-15, FE-ARCH-10..11, TEST-06 | updated | `../architecture/tech-stack.md` | Legacy npm, requirements.txt, no tests |
| Milestones, worktrees, Owner, controlled scope, risk-based debt, early test plan, traceability, concise handoffs | AGENTS.md (stop for approval before every edit) | WF-01..15, TEST-01..09, AGENTS.md | updated | `../workflow/agent-workflow.md` | Not applicable (process) |
| Open questions not made binding | — | OPEN-01..18 | open | `../open-decisions.md` | — |
| Deferred fictional corpus preserved, not designed | — | DEF-01, PROD-12 | aligned with source (recorded only) | `../open-decisions.md` | — |
| Docs-only, no code/deploy/schema changes | — | this branch | updated | `validation-report.md` (diff stat) | — |

## Requirement ID registry
| Prefix | Spec | Kept with updated meaning (old ids) | Retired | New |
|---|---|---|---|---|
| ARCH | backend/architecture | 01–07, 09 | 08 | 10–15 |
| AUTH | backend/auth | 01–04, 06–11 | 05, 12 | 13–21 |
| DOC | backend/documents | 01, 03–05, 07 | 02, 06 | 08–10 |
| ADM | backend/admin-docs | 01–05, 07–09 | 06 | 10–17 |
| ING | backend/ingestion | 02, 05, 07, 09–11 | 01, 03, 04, 06, 08 | 12–22 |
| CHAT | backend/chat | 01–05, 08–10 | 06, 07 | 11–19 |
| MON | backend/monitoring | 02 | 01 | 03–06 |
| LIFE | cross-cutting/document-lifecycle | 01–07 | — | 08–09 |
| FE-ARCH | frontend/architecture | 01–07 | — | 08–13 |
| FE-AUTH | frontend/auth | 01–06 | — | 07–09 |
| FE-CHAT | frontend/chat | 01–03, 05–09 | 04 | 10–13 |
| FE-DOC | frontend/my-documents | 01–06 | — | 07–09 |
| FE-ADM | frontend/admin-upload | 01–10 | — | 11–12 |
| PROD, SEC, EVAL, STACK, INFRA, COST, WF, TEST, M0-EX, M0-AC, OPEN, DEF | new specs | — | — | all |

M0 task ids M0-01..07 and acceptance criteria M0-AC01..09 keep the source numbering. M0-EX1..6 (exit criteria) and M0-AC10 (outbox recovery) were added here and need confirmation (see `validation-report.md`).
