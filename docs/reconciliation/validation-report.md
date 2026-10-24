# Validation report (docs reconciliation 2026-10-24)

Branch `docs/requirements-reconciliation`. This change is **documentation only**: no source code, migrations, packages, infra or deployment were touched, and nothing was merged or pushed.

## 1. Static checks run
| # | Check (source 90 "Minimum static checks") | Command / method | Result |
|---|---|---|---|
| 1 | Inventory `.md` files; references and links resolve | Throwaway Python script (outside the repo) that resolves every backticked `*.md` path and every markdown link, relative to the file and to the repo root. Run on 28 files; the handoff package is excluded. | **Pass** on the final run: 0 broken links. Earlier runs failed with 4 broken links: 3 were reconciliation reports not yet written, now written; 1 was the forward reference `docs/milestones/M0/tasks.md`, which is intentional (created at M0 start, WF-10) and now excluded from the check. |
| 2 | Search for contradictory **target** prescriptions (`JWT`, `Celery`, `Redis`, `Chroma`, `gdown`, `WebSocket`, `npm`, `JSX`, direct `gpt-4o-mini`) outside sections labeled legacy | Same script: keyword scan of lines outside the "Current implementation", "Known gaps", "Retired", "Explicit exclusions" and "Commands" sections | **Pass with manual review**: 14 hits outside those sections, all reviewed by hand. 11 are "Status: … legacy …" lines, 1 is the AGENTS.md "Current code is LEGACY" line, and 2 are AUTH-18 prohibiting JWT (requirement + test). None prescribes a legacy technology as target. |
| 3 | Requirement ID uniqueness and test coverage | Script parses every `ID` table (definitions; "Retired" sections counted separately) and every `Req` table (coverage, including ranges like `PROD-06..09` and `X-05/08`) | **Pass**: 0 duplicate definitions, 0 references to undefined IDs, 319 active IDs and 15 retired IDs. On the first run 37 active IDs had no test row; test or evidence rows were added and the count is now **0 untested**. Process/catalog IDs (WF, STACK, TEST, OPEN, DEF, M0 task ids, M0-EX, M0-AC) are exempt, since they are evidence-by-review or are themselves tests. |
| 4 | Compare the source package file by file | Manual | Done: `requirements-coverage.md` |
| 5 | Inspect AGENTS.md for the old "await approval before each edit" mandate | `grep -rn "Stop and wait\|wait for the user's approval before" AGENTS.md CLAUDE.md docs` (handoff and reconciliation excluded) | **Pass**: no matches. The old rule is replaced by milestone-level gates (WF-06, WF-13). |
| 6 | `git diff --check` and docs-only diff | `git diff --cached --check`; `git diff --cached --name-only -- . ':!docs' ':!AGENTS.md' ':!CLAUDE.md'` | **Pass**: no whitespace errors, and 0 files changed outside `docs/`, `AGENTS.md` and `CLAUDE.md`. Git warns that LF will become CRLF on Windows checkout (autocrlf). This is informational, not an error. |
| 7 | Flag impossible or unsafe requirements and cost/plan contradictions | Manual | See §3 and `../open-decisions.md` (OPEN-10, OPEN-11) |

**Tools not available:** no markdown linter or link-checker is installed, and installing one was out of scope (no package installs). Anchor (`#section`) targets were not validated, because the docs use no anchor links.

**Limitation:** the script's legacy-term scan works on keywords and section headings, so semantic contradictions were checked manually (§2).

## 2. Checklist (source 90 "Documentation acceptance")
| Item | Result | Evidence |
|---|---|---|
| All old docs mapped to target topics; no orphan spec or broken link | **Pass** | `requirements-coverage.md`; all 13 previous specs were updated in place; check 1 |
| AGENTS.md, CLAUDE.md, docs/README.md and index updated for the agent workflow; no blanket per-edit approval | **Pass** | `../../AGENTS.md`, `../../CLAUDE.md`, `../README.md`; check 5 |
| Stable IDs and positive/negative/error tests; Known gaps separate from target | **Pass** | check 3; every spec has "Target requirements" plus "Current implementation (LEGACY)" and "Known gaps" |
| Cross-refs correct; no contradictory status codes, visibility rules or auth schemes | **Pass (manual)** | SEC-01..03 is the single source. DOC-05, ADM-01, ING-11 and FE-ADM-01 match it. One internal inconsistency was found and fixed during the work: "current revision" vs replacement candidate across SEC-07, LIFE-02 and ADM-15, now defined in `../backend/documents.md`. |
| Product: Demo Mode, registered/anonymous identities, seeded departments, no public Admin signup | **Pass**; **open** OPEN-12, OPEN-13 | PROD-01..05, AUTH-04, AUTH-16, AUTH-20 |
| Backend: opaque DB session hash, CSRF, Argon2id; no JWT target | **Pass**; mechanism **open** OPEN-04 | AUTH-06, AUTH-10, AUTH-14, AUTH-18 |
| ACL: owner ≠ access, join rows, 401/403/404, department isolation | **Pass** | SEC-01..10 |
| PDF: private R2, React-PDF viewer, page deep links, no Drive/gdown | **Pass** | DOC-04, DOC-09, FE-DOC-07..09, ADM-06/ING-01 retired |
| Ingestion: ZIP flow, R2, signed QStash Worker, outbox + recovery, at-least-once, leases, atomic revisions, soft delete | **Pass** | ADM-08, ADM-11..15, ING-12..20, LIFE-06..09 |
| Streaming: SSE Fetch POST + AbortController; job status SSE from DB; no Redis pub/sub or WebSocket target | **Pass** | CHAT-03, CHAT-12, ING-05, ING-07; ING-08 retired |
| AI: LlamaIndex, OpenRouter chat, direct embeddings, PyMuPDF4LLM, page-bounded splitter, SQL before Top-K, threshold, citation checks | **Pass**; model and threshold **open** | CHAT-04, CHAT-11, CHAT-16, ING-02, ING-18, SEC-08 |
| Evaluation: human-verified golden set, security hard failures, progressive gates, reproducible reports | **Pass** | EVAL-01..10 |
| Frontend stack | **Pass** | FE-ARCH-01..13, STACK-01..08 |
| Infrastructure | **Pass**; feasibility **open** | INFRA-01..10, STACK-21..29 |
| Tooling | **Pass** | STACK-30..36 |
| Milestones, worktrees, Owner, controlled scope, risk-based debt, early Test Plan, traceability, handoffs | **Pass** | WF-01..15, TEST-01..09 |
| Open questions not made binding | **Pass** | `../open-decisions.md`; specs reference OPEN ids |
| Deferred corpus preserved, not designed | **Pass** | DEF-01, PROD-12 |
| No code, deploy or schema changes | **Pass** | check 6 |

## 3. Uncertain items and judgment calls (need user review)
1. **IDs added beyond the source.** M0-EX1..6 number the source exit criteria. **M0-AC10** (outbox recovery test) was added so that "recovery feasibility proven" is testable. Confirm in M0 planning.
2. **Requirements carried over from the previous repo spec.** These don't conflict with the source but the source doesn't state them: AUTH-03 password policy (OPEN-15) and ADM-05 "at least one allowed department" (OPEN-16).
3. **Interpretations, recorded as OPEN rather than decided:**
   - OPEN-12: which departments a user may select.
   - OPEN-13: the Admin's access in user-facing paths.
   - OPEN-14: error contract details, including the code for a missing active department and the duplicate-email/enumeration posture.
   - OPEN-17: text-less PDFs, interim "failed".
   - OPEN-18: repo layout migration.
4. **Derived detail requirements** (reasonable consequences of the source, flagged for awareness):
   - verification tokens expire and can't be forged (AUTH-13)
   - PDF bytes responses are not publicly cacheable (DOC-04)
   - a page outside the range returns a validation error (DOC-09)
   - markdown rendered without raw HTML (FE-CHAT-05)
   - SSE parser buffering (FE-CHAT-13)
   - the AI usage-record fields (MON-02)
   - audit events (AUTH-21, ADM-17)
   - a lint rule against inline layout styles (FE-ARCH-08 test)
5. **Retired IDs.** 15 IDs whose meaning conflicts with the source were retired, not deleted. In particular, CHAT-06/07 (agent tools) were retired as an interpretation of "keep control in application code". If tool-calling is wanted later, that is a WF-05 scope decision.
6. **Revocation vs delivered text (OPEN-11).** The specs say what the server can do (stop the stream, redact history). They state explicitly that delivered text can't be recalled. The exact redaction UX is not decided.
7. **Cost target (OPEN-10).** It is documented as aspirational and verified by the spike; nothing guarantees it.
8. **The handoff package path is nested** (`docs/knowserve_requirements_handoff/knowserve_requirements_handoff/`). It was left in place as provided and committed as the read-only source of truth. Flattening it is optional.
9. **`frontend/README.md`** is the unmodified Vite template. It's not a spec, so it was left unchanged; it is legacy.

## 4. Current-code discrepancies
Every target requirement is **not implemented**. The full list, with the actively unsafe legacy behaviors, is in `legacy-conflicts.md` §2.
