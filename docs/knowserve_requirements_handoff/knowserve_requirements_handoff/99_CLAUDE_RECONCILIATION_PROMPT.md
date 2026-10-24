# Paste to Claude Code — KnowServe docs reconciliation (DOCS ONLY)

You are the Planning & Integration Owner for the **documentation reconciliation phase**, not yet the implementation phase.

## Input
I provide a source-of-truth package `knowserve_requirements_handoff/` containing topical decision summaries (00–09), a validation checklist (90), and a preliminary snapshot audit (91). Read **ALL** those files first. Then inspect **ALL existing repository Markdown specs**, including `AGENTS.md`, `CLAUDE.md`, `docs/README.md` and related documents. Do not treat legacy code as desired architecture.

## Task
1. Inventory and map current documentation against the approved topical requirements. Create a concise discrepancy matrix (existing claim → required claim → impacted paths).
2. Update the existing Markdown specs **in-place by topic**. Introduce narrowly targeted new Markdown docs only if they materially improve navigability (e.g. requirements: evaluation, deployment, testing/workflow, M0). Preserve useful stable requirement IDs, reconcile duplicates and maintain the docs index/links.
3. Clearly separate `Target requirements` from `Current implementation / Known gaps`. Old backend code remains on Celery/Chroma/Redis/JWT/etc until later implementation; do not pretend it has been migrated.
4. Describe chosen stack, security behavior, document lifecycle, RAG/evaluation, parallel-agent workflow and M0 acceptance plan in coherent cross-linked specs. Include acceptance/test traceability wherever requirements are testable.
5. Update `AGENTS.md` and `CLAUDE.md` to instruct future Agents: approved current contracts, owner-led parallel work, limited review gates, scope control, milestone handoff, and reading topical docs. Remove old blanket rule to stop for user permission before each change.
6. Produce `docs/reconciliation/requirements-coverage.md`, `docs/reconciliation/legacy-conflicts.md`, and `docs/reconciliation/validation-report.md` (names adaptable if repo conventions warrant). Validation report must include every failed/uncertain check and current-code discrepancies.
7. Validate the **documentation**: cross-links, requirement IDs, redundant/conflicting text, checked open issues; run `git diff --check` and any available docs-only static tools. Show changed-file list and a concise explicit statement whether each topic is `aligned`, `updated`, `open`.

## Hard guardrails
- **NO SOURCE CODE MODIFICATIONS, NO DB MIGRATIONS, NO INFRA APPLY, NO DEPLOYMENT, NO INSTALLING PACKAGES, NO SECRETS.** Documentation-only work.
- Keep all agreed decisions; **do not silently decide** unresolved questions (M0 shared-core ownership, exact price/quotas, exact LLM model, thresholds).
- Don't overengineer, introduce speculative abstractions or rewrite tree layout at this stage.
- Avoid touching `.git` or tracked binary data. Preserve repository history.
- If multiple old docs conflict, reconcile by source package and report ambiguity; don't label future requirements as implemented.
- Work on a dedicated branch/worktree; present resulting diff and validation report for my approval; **do not merge**.

## Response format
A. Summary of docs updated and added, with paths.
B. Requirements coverage matrix (topic → docs + status).
C. Conflicts found and resolutions; remaining questions.
D. Validation commands/checks and actual outcomes, including failures.
E. Current code gaps explicitly identified; recommended implementation order.
F. Exact branch name / commit(s) and a note that nothing was merged or deployed.

**Completion criterion:** I can review an explicit docs-only PR/diff and evidence that repo documentation faithfully mirrors all approved KnowServe decisions before authorizing M0 code work.
