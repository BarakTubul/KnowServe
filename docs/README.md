# Writing specs

Each spec is a short, self-contained markdown file for one feature area. Keep them small so an agent can load only what it needs.

## Template
```markdown
# <Feature>

## Purpose
One or two sentences.

## Requirements
| ID | Requirement |
|---|---|
| XXX-01 | Testable statement ("The system must ...") |

## Behavior / API
Endpoints, payloads, status codes, state transitions.

## Files
Paths of the code that implements this.

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| XXX-01 | unit / integration / system | Given ... when ... | ... |

## Known gaps
Where current code differs from the requirements, or open questions. Remove an item when fixed.

## Related docs
Links to other specs.
```

## Rules
- Requirement IDs are stable: prefix per area (`AUTH`, `CHAT`, `DOC`, `ADM`, `ING`, `LIFE`, `FE-*`), never reuse a number.
- Every requirement has at least one row in "Required tests". Test names should include the ID.
- Test levels: **unit** = one function/class with dependencies mocked; **integration** = FastAPI `TestClient` with test DB (Redis/Celery/Chroma faked); **system** = full stack incl. worker.
- Update the spec in the same change as the code.
- Add new specs to the Doc index in `AGENTS.md`.
