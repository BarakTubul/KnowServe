# Backend admin documents

## Purpose
Admin-only management of the document catalog: list everything, add a document (which triggers ingestion), change which departments can access it, delete it.

## Requirements
| ID | Requirement |
|---|---|
| ADM-01 | All `/admin/docs/*` routes require an admin; others get 403, unauthenticated 401. |
| ADM-02 | `GET /admin/docs/` returns every document with id, title, source_url, status, allowed_departments (names), allowed_department_ids, is_active. |
| ADM-03 | `POST /admin/docs/` with `{title, source_url, allowed_department_ids}` creates a document with status `pending` and the given department access, dispatches the Celery ingestion task after the commit, and returns `{"id": <id>}`. |
| ADM-04 | If any `allowed_department_ids` entry doesn't exist, return 400 and create nothing. |
| ADM-05 | Creating a document with an empty `allowed_department_ids` is rejected (the UI requires at least one department). |
| ADM-06 | `source_url` must be a Google Drive file link (`https://drive.google.com/file/d/<id>/...`); other values are rejected before a document is created. |
| ADM-07 | `PATCH /admin/docs/{id}/access` replaces the allowed departments, returns the new department names, and invalidates `docs:all` and `docs:access:{dept}` for every department whose access changed (old and new). Unknown doc returns 404. |
| ADM-08 | `DELETE /admin/docs/{id}` removes the DB row and access rows, deletes the document's vectors from Chroma (`db_doc_id`), removes the stored PDF, and invalidates affected caches. Unknown doc returns 404. |
| ADM-09 | After create/update/delete, `GET /admin/docs/` and the affected departments' `/documents/my/access` reflect the change immediately. |

## Behavior / API
- Create flow: validate departments -> insert `Document(status="pending", is_active=True)` -> commit -> `run_ingestion_task.delay(id, source_url, department_ids)`. See `ingestion.md` for what happens next.
- Status values: `pending`, `ingested`, `failed`.
- DTOs: `CreateDocumentDTO`, `UpdateAccessDTO` in `pydantic_schemas/document_schema.py`.

## Files
`routers/admin/docs.py`, `controllers/admin_docs_controller.py`, `services/docs_service.py` (`add_document`, `update_document_access`, `delete_document`, `delete_from_vector_store`), `repositories/document_repository.py`, `pydantic_schemas/document_schema.py`

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| ADM-01 | integration | Each route as employee / anonymous | 403 / 401 |
| ADM-02 | integration | Two docs with different access | list has both with correct fields |
| ADM-03 | integration | Valid create (Celery `.delay` mocked) | 200 `{id}`; row `pending`; access rows created; `.delay` called once with (id, url, dept ids) after commit |
| ADM-04 | integration | Create with unknown dept id | 400; no document row; `.delay` not called |
| ADM-05 | integration | Create with `[]` | 4xx; no row |
| ADM-06 | unit | Non-Drive URL, malformed Drive URL, valid Drive URL | rejected, rejected, accepted |
| ADM-07 | integration | Change access A,B -> B,C | response lists B,C; caches for A, B and C invalidated |
| ADM-07 | integration | Patch unknown id | 404 |
| ADM-08 | integration | Delete existing doc (Chroma + file mocked) | 200; row gone; Chroma delete called with `{"db_doc_id": id}`; PDF removed; caches invalidated |
| ADM-08 | integration | Delete unknown id | 404 |
| ADM-09 | integration | Create then list as admin and as allowed employee (cache primed before) | new doc visible to both |

## Known gaps
- ADM-05 and ADM-06 are not enforced by the backend or the DTO (ADM-05 only by the UI). A bad Drive URL is accepted, the document is created `pending`, and only the worker later fails it.
- ADM-07: only the *new* department ids are invalidated, so departments that lost access keep seeing the doc until the 15-minute TTL.
- ADM-08: the PDF in `static/docs` is not deleted. Non-existent docs return 404, but the Chroma delete runs only after DB commit, so a Chroma failure leaves orphan vectors.
- If `.delay()` fails (Redis down) the document stays `pending` forever with no error returned.
- `is_active` is stored but never used.
- Router `except Exception` in `create_document` swallows details.

## Related docs
`ingestion.md`, `documents.md`, `../cross-cutting/document-lifecycle.md`, `../frontend/admin-upload.md`
