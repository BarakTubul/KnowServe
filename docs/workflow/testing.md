# Testing strategy and traceability

**Status:** Approved process and target tooling. Not implemented: the legacy repo has no tests and only `backend/pytest.ini`.

## Requirements
| ID | Requirement |
|---|---|
| TEST-01 | Acceptance criteria produce an **early Test Plan** during milestone planning. Tests are written in parallel with the code, and the plan is updated for the edge cases actually found. |
| TEST-02 | Tests run in tiers: targeted tests while coding; cross-module integration tests at merge points; full CI tests, security tests and the relevant evaluation at the milestone PR; production smoke tests after deployment. |
| TEST-03 | The milestone **Review Package** has a requirement-to-test traceability table: requirement id, acceptance criterion, test path/type, actual CI result/evidence, positive/negative/error scenarios, uncovered gaps and quality-gate state. Critical functional, security or auth gaps block merge; non-critical gaps are shown for human decision. |
| TEST-04 | A **test impact map** is maintained manually per module and risk. There is no automatic impact engine. |
| TEST-05 | AI evaluation is progressive, per EVAL-06. Security checks are hard gates from day one (EVAL-05). |
| TEST-06 | Tooling: backend uses pytest, pytest-asyncio and HTTPX, with integration tests against **real PostgreSQL + pgvector** (not SQLite or mocks for permission SQL). Frontend uses Vitest + React Testing Library. E2E uses Playwright, staged by milestone. |
| TEST-07 | Test names or docstrings reference the requirement id they cover (for example `test_sec_02_forbidden_pdf_returns_404`). |
| TEST-08 | Every testable requirement has at least one positive test, and a negative or error test where applicable, listed in its spec's "Required tests" table. |
| TEST-09 | External providers (QStash, R2, OpenRouter, OpenAI embeddings, Resend) are faked in unit and integration tests. Real-provider calls happen only in deployment smoke tests and opt-in real-model eval runs. |

## Test levels used in specs
| Level | Meaning |
|---|---|
| unit | one function or class; dependencies faked |
| component | one React component/page with mocked API (Vitest + RTL) |
| integration | API/Worker via HTTPX against a real Postgres+pgvector; external providers faked |
| e2e | Playwright against the local Compose stack or a deployment smoke |
| eval | evaluation harness case (`../cross-cutting/evaluation.md`) |
| review / spike report | documented evidence, not automated |

## Current implementation (LEGACY)
- There are no backend or frontend tests. A `tests/` tree existed earlier in git history and was deleted.
- `pytest-asyncio` is configured in `pytest.ini` but is not in `requirements.txt`.
- The frontend has no test runner, only `npm run lint`.

## Related docs
`agent-workflow.md`, `../cross-cutting/evaluation.md`, `../milestones/M0/plan.md`, `../README.md`
