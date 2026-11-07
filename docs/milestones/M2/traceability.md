# M2 traceability table (TEST-03)

Status of 2026-11-07, branch `m2/integration`, draft PR 32. Test files: `apps/api/tests/test_m2_*.py`, `packages/backend_core/tests/test_m2_*.py`, `apps/frontend/src/features/documents/**/*.test.tsx`, `apps/frontend/functions/api/proxy.test.ts`.

Evidence legend: **local** = run on the integration worktree (550 Python tests and 162 frontend tests at commit `4554862`, plus the later targeted runs recorded in `tasks.md`). **CI** = GitHub `ci` on draft PR 32, 8 of 8 checks passed on `19d39b0`; the later commits have not been re-checked here. Reviews: CP1 (schema, predicate, 404) and CP2 (M2-02, M2-03) found no blocking issue.

A row is **open** when evidence is missing; open rows are gaps the user has to see (M2-EX1).

| Criterion | Requirement | Tests (positive / negative / error) | Evidence | State |
|---|---|---|---|---|
| M2-AC01 | SEC-07, DOC-01 | `test_sec07_states_matrix`, `test_doc01_states_matrix_lists_only_ready_current_revisions` (ready listed; queued, processing, failed, deleted, no revision hidden); `test_doc08_order_is_created_at_desc_then_id_desc` | local, CI | covered |
| M2-AC02 | SEC-04, DOC-07 | `test_sec04_owner_label_grants_nothing_and_access_rows_do`, `test_sec04_owner_a_allowed_c_only`, `test_sec17_owner_label_and_admin_kind_grant_nothing` | local, CI | covered |
| M2-AC03 | SEC-02, DOC-05, SEC-01 | `test_doc05_every_cause_gives_the_identical_404` (both routes, `request_id` excluded); `test_q7_malformed_id_gets_the_uniform_404`; `test_doc11_range_on_a_forbidden_document_is_the_uniform_404_not_416`; `test_sec01_no_session_is_401_and_no_department_is_409` | local, CI | covered |
| M2-AC04 | DOC-03, SEC-17 | `test_sec01_no_session_is_401_and_no_department_is_409`, `test_m2_ac05_admin_without_department_gets_409_before_query_validation`, `test_m2_ac05_unauthenticated_is_401_before_query_validation` | local, CI | covered |
| M2-AC05 | DOC-10, SEC-09 | `test_doc10_revoke_then_fetch_and_soft_delete_apply_on_the_next_request`, `test_doc11_revoke_between_two_range_requests`, `test_sec05_revoke_between_two_pages`, `test_doc10_soft_delete_applies_on_next_query` | local, CI | covered |
| M2-AC06 | SEC-06 | `test_m2_ac06_no_unregistered_document_route`, `test_m2_ac06_by_id_routes_apply_the_predicate_matrix`, `test_m2_ac06_list_route_applies_the_predicate_matrix`, `test_sec06_department_in_the_request_is_ignored` | local (CI pending on the latest push) | covered |
| M2-AC07 | DOC-07, DOC-08 | `test_doc07_search_and_owner_filter_intersect_across_pages`, `test_doc07_like_wildcards_are_literal`, `test_doc08_tampered_cursor_is_a_controlled_422`, `test_doc08_out_of_range_cursor_timestamp_is_422_not_500`, `test_doc08_real_cursor_with_edited_payload_is_422`, `test_doc07_malformed_owner_filter_is_422`, `test_doc08_limit_bounds_are_422`, `test_doc08_default_limit_is_20`; UI: `fe_doc_03_...`, `fe_doc_10_load_more_...`, `fe_doc_10_a_filter_change_restarts_...` | local, CI | covered (UI by component tests, no browser e2e) |
| M2-AC08 | DOC-04, DOC-11, ARCH-14 | `test_doc04_streams_the_pdf_with_safe_headers_and_no_storage_url`, `test_doc04_range_header_set_is_identical_on_the_not_found_path`, `test_doc11_valid_single_range_gives_206`, `test_doc11_unsatisfiable_range_gives_416`, `test_doc11_multiple_or_malformed_ranges_are_ignored_and_serve_the_full_body`, `test_doc11_if_range_matches_etag_or_falls_back_to_the_full_body`, `test_doc11_resolve_range_unit`, `test_doc11_range_header_with_unicode_digits_is_ignored`, `test_doc04_filename_sanitizer`, `test_doc05_ready_revision_with_missing_bytes_is_the_uniform_404`, `test_sec13_store_outage_is_503_without_storage_details`, proxy forwarding in `proxy.test.ts` | local, CI | covered against `FakeObjectStore` and a mock R2 transport; **gap: no real R2 bucket** |
| M2-AC09 | DOC-09 | `test_doc09_metadata_and_page_validation`, `test_doc09_page_check_runs_only_after_the_visibility_lookup`, `test_doc09_metadata_exposes_no_storage_fields` | local, CI | covered |
| M2-AC10 | SEC-10, FE-DOC-01 | `fe_doc_01_the_query_key_carries_identity_and_department_and_a_switch_never_shows_the_old_list` (component) | local, CI | **open: browser e2e (Playwright) not yet written** |
| M2-AC11 | SEC-17, OPEN-13 | `test_sec17_owner_label_and_admin_kind_grant_nothing`, `test_m2_ac05_admin_without_department_gets_409_before_query_validation` | local, CI | covered for the regular library, bytes and metadata; the Admin list half is ADM-02 in M3 |
| M2-AC12 | FE-DOC-07..09, PROD-07 | `fe_doc_07_requests_only_the_api_bytes_url_with_credentials`, `fe_doc_08_opens_page_3_and_next_moves_to_page_4_in_the_url`, `fe_doc_08_zoom_...`, `fe_doc_08_an_out_of_range_page_...`, `fe_doc_09_metadata_404_shows_the_neutral_view`, `fe_doc_09_bytes_404_...`, `fe_doc_09_the_404_view_is_identical_for_every_cause` | local, CI | **open: browser e2e and a real pdf.js render not yet run** (tests replace `react-pdf`) |
| M2-AC13 | FE-DOC-02, 04, 05, 06, PROD-06, PROD-13 | `fe_doc_02_shows_loading_then_the_empty_message`, `fe_doc_04_05_items_show_filename_...`, `fe_doc_06_a_filter_with_no_hits_...`, `fe_doc_02_prod_13_errors_render_a_friendly_message_never_the_api_text`, `fe_doc_05_the_dashboard_links_to_the_library` | local, CI | covered |
| M2-AC14 | ARCH-11, INFRA-05, TEST-11, TEST-16 | `test_m2_ac14_schema_has_document_tables`, `test_current_revision_must_belong_to_same_document`, `test_ready_revision_requires_page_count`, `test_m2_downgrade_0003_removes_document_tables_and_upgrades_again`; rollback note `docs/architecture/rollback.md` | local, CI | covered; the INFRA-05 checklist answer goes in the milestone PR text |
| M2-AC15 | D1 | `test_m2_ac15_*` (determinism, committed PDFs, shape and ids, idempotency, no overwrite, hand-edited rows flagged `incomplete`, filesystem twice), `test_sec04_sec05_seed_visibility_per_department` | local, CI | covered locally; **gap: the owner-run production seed has not happened** |
| M2-AC16 | TEST-15, A7, D1 | none | none | **open: needs M2-00c (R2) and the approved production migration; not started** |
| M2-AC17 | D5, TEST-11 | migrations `0001` to `0003` and the full suite on `pgvector/pgvector:0.8.6-pg18` | CI (8 of 8, PR 32); ADR 0002 and the M2-PG handoff note | covered |
| M2-AC18 | D2, TEST-13, TEST-14 | review of `docs/architecture/ci-cd-proposals.md`; user decisions of 2026-11-07 recorded in `open-decisions.md` | review | covered as docs; no implementation by design |
| M2-AC19 | AUTH-35, SEC-14 | none until the 2026-11-08 03:00 UTC run | pending | **open: read-only check of the Worker log and the `demo.cleanup.run` audit row after the run** |
| M2-AC20 | INFRA-05, TEST-16 | `docs/architecture/rollback.md` (review) and the downgrade test above | review | covered; the procedure itself has not been exercised |
| M2-AC21 | SEC-18, MON-04, MON-05, AUTH-15 | M2-PRIV tests (audit rows carry no address, 429 still works on the hashed key, log capture finds no address, no counter key contains an address) | pending the M2-PRIV merge | **open until M2-PRIV is integrated.** The production-data half is deferred and non-blocking (OPEN-30); existing production IP data is not claimed clean |
| M2-AC22 | PROD-13, FE-ARCH-14 | `fe_arch_14_*` (code-to-message mapping, generic fallback, 503, network failure, unreadable PDF); Hebrew and selector tests from the Q13 task | local | **partial until the Q13 task is integrated** (English only today) |

## Exit criteria
| ID | State |
|---|---|
| M2-EX1 | This table. Open rows: AC10 and AC12 (browser e2e), AC16, AC19, AC21 and AC22 (pending integration), plus the production halves of AC15 and AC21. |
| M2-EX2 | CI green on `19d39b0` (8 of 8). Re-check after the latest commits are pushed. |
| M2-EX3 | CP1 and CP2 reviews done, no blocking finding. A review of the M2-PRIV and Q13 changes is not yet done. |
| M2-EX4 | Not met: needs M2-00c and the production migration approval. |
| M2-EX5 | Specs updated by each task; the final WF-15 check is part of M2-07. |
| M2-EX6 | Not met: handoff (M2-07) and the user's approval of the milestone PR. |

## Known test limits
- Bytes tests use `FakeObjectStore` and a mock R2 transport. Real R2 behavior, and Cloud Run and Pages Function streaming limits, are unmeasured until the deployed smoke.
- Frontend viewer tests replace `react-pdf`; jsdom has no canvas.
- The shared test database can be busy while several sessions run; the full suite should run on an isolated database when sessions overlap.
