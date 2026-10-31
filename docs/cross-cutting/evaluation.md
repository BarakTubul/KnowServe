# RAG evaluation

**Status:** Target spec. Not implemented: there is no dataset, harness or report in the repo. Deterministic and security checks run from the first affected milestone (M4 for chat). The full suite is M6.

## Purpose
Measure retrieval and answer quality, and catch security regressions, reproducibly. The design of the fictional corpus is deferred (DEF-01) and not decided here.

## Target requirements
| ID | Requirement | Milestone |
|---|---|---|
| EVAL-01 | A hybrid golden dataset combines human-written and LLM-synthetic samples, and **every sample is human-verified**. Each sample has expected sources, pages, department and revision. Cases include negatives, partial, conflicting, multi-turn and prompt-injection. | M4 (seed) / M6 |
| EVAL-02 | Retrieval metrics are computed at document and chunk level: Recall@K, Precision@K and MRR. References stay stable across re-chunking (for example by document, revision and page). | M4/M6 |
| EVAL-03 | Answer and citation quality is judged by deterministic checks, an LLM judge and human calibration. | M6 |
| EVAL-04 | Deterministic citation checks (existence and authorization, CHAT-11) are kept separate from semantic grounding. A citation that exists does not prove the claim is supported. | M4 |
| EVAL-05 | Security failures (leaks, followed injections, forbidden citations) are **hard failures**, reported individually and never hidden inside an aggregate score. | M4 |
| EVAL-06 | Gates are progressive: deterministic and security checks run on every PR; small real-model checks run only for relevant changes; the full real-model suite runs manually or periodically. | M4/M6 |
| EVAL-07 | AI quality thresholds are informational until a baseline exists, and later gate regressions. Threshold values are OPEN-08. | M6 |
| EVAL-08 | The approved baseline is immutable and changes only after human review. Each run records the versions of the dataset, model, config and document revisions. | M6 |
| EVAL-09 | Only suspicious or borderline cases are re-run. Reports distinguish judge stochasticity from model variability. | M6 |
| EVAL-10 | Each run outputs `evaluation_report.md` and `evaluation_results.json`, with per-case details, evidence, deltas, failures, coverage/gaps and provenance. | M4/M6 |

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| EVAL-01 | review | Dataset schema validation | every sample has `verified_by`, expected sources/pages/department/revision and a case type |
| EVAL-02 | unit | Metric functions on hand-computed fixtures | exact Recall@K / Precision@K / MRR |
| EVAL-03 | review | Judge prompt and calibration set | a human-calibrated agreement sample is recorded in the report |
| EVAL-04/05 | unit | Report with one leaked citation and a high aggregate score | run marked failed; the leak listed individually |
| EVAL-06 | CI | PR touching only frontend CSS | no real-model eval triggered; deterministic checks run |
| EVAL-07 | unit | Score below a threshold before / after a baseline exists | informational warning / failing gate |
| EVAL-08 | unit | Run against a changed dataset hash without an approved baseline | comparison refused / flagged |
| EVAL-09 | unit | Borderline case re-run | the re-run is recorded separately with the judge and model seeds/variance noted |
| EVAL-10 | unit | Report generation | both files produced with the required sections and fields |

## Current implementation (LEGACY)
None. The agent prompt in `backend/app/agent/llama_agent.py` contains citation instructions, but nothing verifies them.

## Related docs
`../backend/chat.md`, `security-and-permissions.md`, `../workflow/testing.md`, `../open-decisions.md`
