# Validation report (decisions update, 2026-10-24)

Branch `docs/requirements-reconciliation`. This is the second, incremental pass on top of commit `150b45b` (first reconciliation). It applies the user-approved decisions OPEN-01, 04, 07, 11–18 and the Email OTP requirement. The change is **documentation only**: no source code, tests, dependencies, Dockerfiles, Terraform, CI, migrations or deployments were touched, and nothing was pushed or merged.

The first pass's results (0 broken links, 0 duplicate IDs, 319 active and 15 retired IDs, 0 untested IDs, `git diff --check` clean) are superseded by the run below.

## 1. Checks executed (second pass)
| # | Check | Method | Result |
|---|---|---|---|
| 1 | Markdown inventory and normative docs | Script walk of all `.md` (handoff package excluded as read-only input) | 30 files. Normative: the specs under `docs/{backend,frontend,cross-cutting,architecture,workflow,milestones}`, `docs/open-decisions.md`, `AGENTS.md`, `CLAUDE.md`. Non-normative: `docs/reconciliation/*`, `docs/README.md` (index/rules), the handoff package (source input), `frontend/README.md` (Vite template). |
| 2 | Relative links and backticked `.md` paths | Throwaway Python script outside the repo (no installs) | **Pass** on the final run: 0 broken. The previous run failed with 5 broken path references inside this report (a bare `open-decisions` path and the three request-named report paths); they were fixed. `docs/milestones/M0/tasks.md` is an intentional forward reference (WF-10) and is skipped. |
| 3 | Requirement ID uniqueness | Same script parses every `ID` table | **Pass**: 0 duplicate definitions; 334 active, 15 retired. No ID was renumbered or reused. |
| 4 | References to requirement IDs | Every `PREFIX-n` token across the specs vs the definitions | **Pass**: 0 undefined references (includes the new M1-AC prefix). |
| 5 | Test traceability | Every active testable ID has a "Required tests" row | **Pass**: 0 untested. New IDs AUTH-22..28, SEC-17, ING-23, FE-AUTH-10 and INFRA-11 all have rows. |
| 6 | Legacy terms outside legacy sections (`JWT`, `Celery`, `Redis`, `Chroma`, `gdown`, `WebSocket`, `npm`, `JSX`, `gpt-4o-mini`) | Keyword scan outside "Current implementation", "Known gaps", "Retired", "Explicit exclusions", "Commands" | **Pass with manual review**: 17 hits, all reviewed. 11 status lines and the AGENTS.md line describe legacy code; 2 are AUTH-18 forbidding JWT; 3 are in the M0 plan's "Current structure" and transition steps, which describe the legacy repo and forbid carrying those technologies over. None prescribes legacy tech as target. |
| 7 | Decision status consistency | Script: parse "Resolved decisions" and "Still open" in `../open-decisions.md` | **Pass**: resolved = OPEN-01, 04, 07, 11..18; still open = OPEN-02, 03, 05, 06, 08, 09, 10, 19, 20; no ID in both; every still-open row has class, owner, target milestone and decision criteria. |
| 8 | Stale "open/pending" wording next to resolved IDs in specs | Script regex + manual review | **Pass with manual review**: 3 hits, all false positives (the `open-decisions` filename twice, and "opens the selector"). |
| 9 | Email OTP coverage | Script: presence in auth (BE/FE), security, product, tech stack, monitoring, M1 plan, decision log, AGENTS.md | **Pass**: all present. M0 plan explicitly excludes OTP. |
| 10 | Cross-spec alignment (manual, section level) | Read the changed sections against each other | **Pass**, see §2. |
| 11 | No non-Markdown changes | `git diff --name-only` filtered for non-`.md` | **Pass**: none. |
| 12 | `git diff --check` | as named | **Pass**: exit 0. Git prints LF→CRLF warnings for every touched file (autocrlf); informational, not errors. |

**Not performed:** no markdown linter or link-checker is installed and none was installed. Anchor links were not validated (the docs use none). The handoff package was not re-validated (read-only input). The legacy-term and stale-wording scans are keyword based, so semantics were checked manually.

## 2. Alignment checks (manual)
| Area | Result |
|---|---|
| Product ↔ auth ↔ frontend: department selection, Demo Mode | PROD-04, AUTH-17, FE-AUTH-09, SEC-10 agree: all departments, labeled Demo Mode. |
| Security ↔ documents ↔ admin: Admin rights | SEC-17, PROD-05, DOC-02 (retired reason), DOC-03, ADM-02 agree: no bypass in user paths, all docs only via Admin endpoints. |
| Error contract | ARCH-05 (envelope), security status summary (401/403/404/409/422/503), AUTH-02, AUTH-17, DOC-03, CHAT-05, FE-ARCH-03, FE-AUTH-09 agree. |
| Session/CSRF | AUTH-06, AUTH-14, AUTH-19, INFRA-11, FE-ARCH-02, M0-AC11 agree on `SameSite=Lax`, host-only API cookie, CSRF token + Origin, narrow CORS, M0 domain validation. |
| Revocation | SEC-09, CHAT-02/13/15, FE-CHAT-11, PROD-08 agree with OPEN-11; LIFE-05, DOC-10 unchanged and compatible. |
| Upload permissions | ADM-05, FE-ADM-03, FE-ADM-11, SEC-04/05 agree: owner preselected in the UI only, ≥1 explicit access row, owner never grants access. |
| Text-less PDFs | ING-09, ING-23, ADM-02, ADM-15, ADM-16, FE-ADM-06, SEC-07 agree. |
| Workflow | WF-03, WF-16, AGENTS.md, M0 plan agree; no fixed agent count; human approval of every milestone PR kept (WF-13). |
| Preserved architecture (§4 of the request) | Tech stack rows STACK-01..39 unchanged except STACK-13/14/39 wording; evaluation spec untouched; traceability rules unchanged. |

## 3. Interpretations and items for user review
1. **ZIP default permissions (ADM-05).** The decision asks for "safe validation of any defaulting behavior" in ZIP import. The specs say: a manifest entry should list allowed departments; if the flow defaults to the owner department for an entry that omits them, the preview shows it as an explicit planned access row and only confirmation makes it binding; an explicit empty list is rejected. Confirm, or require explicit lists only.
2. **Admin and Email OTP (OPEN-19).** The decision allows OTP for "existing, email-verified accounts" but the Admin is provisioned out-of-band. The specs treat the Admin as password-only until the user decides.
3. **Derived details** (consequences of the decisions, flagged for awareness):
   - `NO_EXTRACTABLE_TEXT` failures skip automatic retries, since retrying cannot help (ING-23).
   - Replacing a failed first upload uses the ADM-15 replace flow, which stays M5; until then the Admin's options are Retry or delete and re-upload.
   - SSE `error` events reuse the error envelope fields (ARCH-05).
   - The CSRF token delivery detail and the password blocklist / breach-check mechanism are left to M1 ADRs; the breach check must never send the plaintext password to a third party (AUTH-03).
   - OTP request responses for ineligible emails must be identical, including no meaningful timing difference (AUTH-22).
4. **New IDs added beyond the decisions:** SEC-17, INFRA-11, WF-16, ING-23, AUTH-22..28, FE-AUTH-10, M0-AC11, M1-AC01..10, OPEN-19, OPEN-20. M0-AC10/AC11 and M0-EX1..6 need confirmation at M0 plan approval (OPEN-20).
5. **New file `docs/milestones/M1/plan.md`.** It is scope and acceptance criteria only, created so that the Email OTP decision has M1 acceptance criteria. It contains no task graph or implementation tasks.
6. **Report locations.** The request placed the coverage, legacy-conflicts and validation reports directly under `docs/`. They already live in `docs/reconciliation/` and were updated in place rather than moved, to keep links and history stable.
7. **Nested handoff directory** (`docs/knowserve_requirements_handoff/knowserve_requirements_handoff/`). It holds a single copy (no duplicates), so it was left as is to avoid churn; flattening it with `git mv` is optional.
8. **Source package superseded in one place.** Source 01/02/04 asked to hide/redact historical text after revocation; OPEN-11 supersedes that for saved answer text. `docs/README.md` now states that resolved decisions take precedence over the package.

## 4. Contradictions between approved decisions
None found that cannot be resolved from the decisions themselves. One tension is recorded for visibility, not as a blocker: the OPEN-04 custom domain adds cost against the $0–5/month target, so OPEN-10 includes the domain cost and the M0 spike reports it.

## 5. Current-code discrepancies
Every target requirement remains **not implemented**. See `legacy-conflicts.md` §2; rows 25–29 of §1 list the conflicts added in this pass.
