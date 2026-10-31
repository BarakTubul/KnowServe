# KnowServe — Consolidated decision source (2026-10-24)

**Status:** Planning source package for reconciliation into the EXISTING repository. **Not a statement that current code/docs are implemented or compliant.**

## Authority / precedence
1. Explicit decisions in the user–assistant planning conversation, captured in these files.
2. Existing repository specs only where compatible with (1).
3. Existing code describes current implementation, **not the target requirements**.
4. When unclear, label `OPEN` and seek human review; do not silently invent a requirement.

## Scope and use
- These files describe *target behavior and confirmed technical decisions*. They are intended for Claude to update the repo's existing Markdown docs, preserving useful requirement IDs and cross-references whenever possible.
- **Documentation-only phase. Do not implement code, install dependencies, migrate data or deploy.**
- Resolve contradictions across all specs; list gaps between target docs and current code under `Known gaps`.
- Use `99_CLAUDE_RECONCILIATION_PROMPT.md` as the handoff instructions and `90_VALIDATION_CHECKLIST.md` as acceptance checks.

## Topics
| File | Subject |
|---|---|
| 01_PRODUCT_AND_UX.md | Product, personas, demo and interface |
| 02_AUTH_SECURITY_PERMISSIONS.md | Identity, sessions, authorization, threat controls |
| 03_DOCUMENTS_AND_INGESTION.md | Storage, upload, lifecycle, jobs |
| 04_RAG_CHAT_EVALUATION.md | Search, responses, citations and evaluation |
| 05_TECH_STACK.md | Confirmed tech and environment |
| 06_INFRA_DEPLOYMENT_COST.md | Deployment, limits, monitoring and costs |
| 07_AGENT_WORKFLOW.md | AI agents, reviews, milestones and tests |
| 08_M0_FOUNDATION_PLAN.md | Provisional M0 plan and dependencies |
| 09_OPEN_DECISIONS.md | Unresolved or deferred decisions |
| 90_VALIDATION_CHECKLIST.md | Coverage and contradiction audit |
| 91_REPO_DELTA_SNAPSHOT.md | Preliminary discrepancies visible in uploaded ZIP |
| 99_CLAUDE_RECONCILIATION_PROMPT.md | Instructions for Claude Code |

## Required output from Claude
- Updated repository Markdown specs, README index, AGENTS.md and CLAUDE.md instructions.
- A requirement-to-document coverage matrix and a report of contradictions eliminated/open gaps.
- A complete changed-file list, checks run, and explicit `not implemented` statements where the code has not been migrated.
- A **docs-only** PR/diff for human inspection; no automatic merge.
