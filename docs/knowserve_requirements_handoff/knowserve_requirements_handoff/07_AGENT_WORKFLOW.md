# Development workflow with parallel AI agents

## Governance
- Architecture follows small usable vertical slices, grouped into **relatively large milestones with few PRs**. Multiple small commits and incrementally integrated tested deliverables inside milestone branch.
- One **Planning & Integration Owner** sets dependency graph, per-milestone plan, upfront shared contracts, assignments/ownership, integration, CI verification and final PR. Agents use isolated Git worktree + branch; no two agents mutate a common shared contract without Owner approval/coordination.
- Implementation Agents own bounded modules; they can fix local defects and required edge cases autonomously. Architectural, interface, security, scope, cost or crosscutting changes escalate. **Controlled Scope Changes:** new features/major expanded scope require user's approval; correctness and edge cases implied by existing requirements handled in milestone.
- Review primarily at tested **integration points**, for risky changes by independent Review Agent, and before final milestone PR; not after every edit/commit.
- Stable milestone branch integrates deliverables through isolated trial integration/worktree; merge only after relevant tests; revert/fix failure without blocking unrelated agents.
- Agent hands off summary of branch/commit, files/contracts, tests + evidence, risks, known gaps and integration instructions. Owner independently verifies results, doesn't trust 'tests pass' claim.
- Bounded attempts to resolve blockers then escalate summary of attempted fixes/options; keep independent tasks working.
- One per-milestone `docs/milestones/Mx/tasks.md` Task Board, updated by Owner at meaningful changes (not every commit). Short ADRs only for important design choices.
- **Technical debt risk-based:** critical security, correctness, reliability and serious future development blockers fixed before merge; cosmetic/noncritical improvements documented and deferred.
- **Milestone handoff** concise at completion: implemented state, shared contracts, tests/evidence, merged SHA, ADRs, limitations, debt, next milestone notes; references existing docs instead of duplicating.
- User explicitly approves final Milestone PR to main before automatic deploy. Do not invent continuous separate PR review gates.

## Testing and approvals
- Acceptance criteria lead to an **early Test Plan** in milestone planning; tests implemented in parallel with code and plans updated for actual edge cases.
- Tiered: targeted tests during coding; cross-module integration tests at merge point; full CI tests/security and relevant evaluation at milestone PR; production smoke tests after deployment.
- Requirement-to-Test Traceability in **Review Package**: requirement ID, acceptance criterion, test path/type, actual CI result/evidence, positive/negative/error scenarios, uncovered gaps and quality gate state. Functional/security/auth critical gaps block merge; noncritical gaps visible for human decision.
- Test impact map manually maintained per module/risk, no complicated automatic impact engine.
- Progressive AI eval: fast deterministic checks every PR, selected real AI evaluations for relevant changes, full benchmark occasional; quality thresholds after baseline; security checks hard gates from day one.

## Milestone outline (provisional)
M0 Foundation/CI/IaC/early deployment spike; M1 Authentication & Demo; M2 Docs Library & Access; M3 Admin Upload & Ingestion; M4 RAG Chat & Citations (**first usable MVP**); M5 Admin Lifecycle/Hardening; M6 Evaluation & Production hardening. Security tests from earliest affected milestone; not postponed to M6. Parallelize nondependent slices where useful.
