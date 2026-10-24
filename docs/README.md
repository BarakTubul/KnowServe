# KnowServe specs

Specs describe the **target** system, using the approved decisions in `knowserve_requirements_handoff/` as amended by the later user-approved decisions in `open-decisions.md` ("Resolved decisions"), which take precedence where they differ (for example OPEN-11 on historical chat answers). Each spec also records how the **legacy** code differs. The code in `backend/` and `frontend/` is legacy until migrated milestone by milestone. A requirement being in a spec does **not** mean it is implemented.

## Index
| Area | Spec | ID prefix |
|---|---|---|
| Product, personas, routes, scope | `cross-cutting/product-and-ux.md` | PROD |
| Access control, status codes, isolation, defense in depth | `cross-cutting/security-and-permissions.md` | SEC |
| Document lifecycle end to end | `cross-cutting/document-lifecycle.md` | LIFE |
| RAG evaluation | `cross-cutting/evaluation.md` | EVAL |
| Tech stack + exclusions | `architecture/tech-stack.md` | STACK |
| Infrastructure, deployment, cost controls | `architecture/infrastructure.md` | INFRA, COST |
| Backend structure and conventions | `backend/architecture.md` | ARCH |
| Auth, sessions, demo, departments | `backend/auth.md` | AUTH |
| Library and protected PDF access | `backend/documents.md` | DOC |
| Admin document management | `backend/admin-docs.md` | ADM |
| Ingestion: outbox, QStash, Worker | `backend/ingestion.md` | ING |
| RAG chat and citations | `backend/chat.md` | CHAT |
| Logging, audit, usage accounting | `backend/monitoring.md` | MON |
| Frontend structure and conventions | `frontend/architecture.md` | FE-ARCH |
| Frontend auth, demo, department switch | `frontend/auth.md` | FE-AUTH |
| Frontend chat | `frontend/chat.md` | FE-CHAT |
| Library + PDF viewer | `frontend/my-documents.md` | FE-DOC |
| Admin UI | `frontend/admin-upload.md` | FE-ADM |
| Agent workflow, milestones | `workflow/agent-workflow.md` | WF |
| Testing strategy and traceability | `workflow/testing.md` | TEST |
| M0 plan, repository transition and test plan | `milestones/M0/plan.md` | M0-EX, M0-, M0-AC |
| M1 scope and acceptance criteria | `milestones/M1/plan.md` | M1-AC |
| Resolved decisions (decision log), open decisions, tensions, deferrals | `open-decisions.md` | OPEN, DEF |
| Reconciliation reports (2026-10-24, incl. the decisions update) | `reconciliation/requirements-coverage.md`, `reconciliation/legacy-conflicts.md`, `reconciliation/validation-report.md` | — |
| Approved source package (read-only input) | `knowserve_requirements_handoff/knowserve_requirements_handoff/00_README.md` | — |

## Spec template
```markdown
# <Feature>

**Status:** Target spec (milestone). Implementation state in one line.

## Purpose
## Target requirements
| ID | Requirement | Milestone |
### Retired IDs (do not reuse)
| ID | Was | Reason |
## Required tests
| Req | Level | Scenario | Expected |
## Current implementation (LEGACY, not migrated)
## Known gaps
## Related docs
```

## Rules
- **IDs are stable.** Never reuse a number. When a requirement no longer applies, move it to "Retired IDs" with a reason. When a requirement's meaning evolves, keep the ID and update the text.
- **One normative home per rule.** Cross-cutting rules (SEC, COST, MON) are defined once; feature specs reference those IDs rather than restating them.
- **Target vs legacy.** "Target requirements" describe the desired behavior. "Current implementation (LEGACY)" and "Known gaps" describe today's code. Never mark a requirement as implemented without test evidence (TEST-03).
- **Tests.** Every testable requirement has at least one row in "Required tests", including negative/error cases where applicable (TEST-08). Test levels are defined in `workflow/testing.md`. Test names include the ID (TEST-07).
- **Open items.** Do not decide anything listed under "Still open" in `open-decisions.md` inside a spec; reference its OPEN-id instead. Items under "Resolved decisions" are binding and their OPEN-id is kept for provenance.
- Update the spec in the same change as the behavior (WF-15), and add new specs to this index and to the AGENTS.md doc index.
