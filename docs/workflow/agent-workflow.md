# Development workflow with parallel AI agents

**Status:** Approved process. Applies to all milestone work, starting with M0 once the user authorizes implementation.

## Roles
- **User**: approves milestone plans, material scope/contract/architecture changes and the final milestone PR.
- **Planning & Integration Owner** ("Owner"): owns the dependency graph, the milestone plan, the shared contracts, assignments, integration, CI verification and the final PR. May delegate implementation.
- **Implementation Agents**: own bounded modules in their own worktrees.
- **Independent Review Agent**: reviews high-risk changes and the final milestone integration.

## Requirements
| ID | Requirement |
|---|---|
| WF-01 | Work is organized as small usable vertical slices grouped into **relatively large milestones with few PRs**. Inside the milestone branch, work lands as multiple small commits and incrementally integrated, tested deliverables. |
| WF-02 | The Owner sets the dependency graph, the per-milestone plan, the upfront shared contracts (API/OpenAPI + errors, config, DB/migration ownership, job envelope, logging ids, health, deploy interface), assignments, integration, CI verification and the final PR. |
| WF-03 | Each agent works in an isolated Git worktree and branch. No agent changes a shared contract (OpenAPI, DB schema/migrations, shared core, job envelope, config keys) without Owner coordination. Shared core ownership model: OPEN-01. |
| WF-04 | Implementation Agents fix local defects and the edge cases implied by existing requirements **without asking**. They escalate architecture, interface, security-model, scope, cost and cross-cutting changes to the Owner. |
| WF-05 | **Controlled scope changes**: new features or major scope expansion need the user's approval. Correctness and edge cases implied by existing requirements are handled inside the milestone. |
| WF-06 | Review happens at tested **integration points**, by the independent Review Agent for risky changes, and before the final milestone PR. There is **no review or approval gate after every edit or commit**. |
| WF-07 | A stable milestone branch integrates deliverables through a trial-integration worktree and merges only after the relevant tests pass. A failing deliverable is reverted or fixed without blocking unrelated agents. |
| WF-08 | Agent handoff to the Owner: branch/commit, files and contracts touched, tests with evidence, risks, known gaps and integration instructions. The Owner verifies independently and does not trust a "tests pass" claim. |
| WF-09 | Blockers get a bounded number of attempts, then escalate with a summary of the attempts and options. Independent tasks continue meanwhile. |
| WF-10 | Each milestone has a Task Board at `docs/milestones/Mx/tasks.md`, updated by the Owner at meaningful changes (not every commit). Important design choices get short ADRs in `docs/adr/`. |
| WF-11 | Technical debt is handled by risk. Critical security, correctness and reliability issues, and serious blockers for future work, are fixed before merge. Cosmetic and non-critical items are documented and deferred. |
| WF-12 | Each milestone ends with a concise **milestone handoff**: implemented state, shared contracts, tests/evidence, merged SHA, ADRs, limitations, debt and notes for the next milestone. It references the specs instead of duplicating them. |
| WF-13 | The user explicitly approves the final milestone PR to `main`, and the automatic deploy (INFRA-04) follows. No other separate PR review gates are added. |
| WF-14 | Provisional milestones: **M0** Foundation/CI/IaC/deployment spike, **M1** Authentication & Demo, **M2** Documents Library & Access, **M3** Admin Upload & Ingestion, **M4** RAG Chat & Citations (**first usable MVP**), **M5** Admin Lifecycle/Hardening, **M6** Evaluation & Production hardening. Security tests start in the earliest affected milestone. Independent slices may run in parallel. |
| WF-15 | Specs are updated in the same change as the behavior they describe (requirements, tests table, current implementation / known gaps). |

## Evidence
These are process requirements, so they are checked by review rather than automated tests:
- WF-08: the handoff note exists.
- WF-10: the task board and ADRs exist.
- WF-12: the milestone handoff doc exists.
- WF-13: the PR approval is recorded.

Test-related process rules are in `testing.md`.

## Current state
No milestone has started. This repository is in the **documentation reconciliation phase**. Code work (M0) starts only after the user approves the docs-only PR and authorizes M0.

## Related docs
`testing.md`, `../milestones/M0/plan.md`, `../open-decisions.md`, `../../AGENTS.md`
