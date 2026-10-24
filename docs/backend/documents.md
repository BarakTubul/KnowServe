# Backend documents (user-facing)

## Purpose
Let authenticated users list the documents their department can access and download the PDF. Admin management is in `admin-docs.md`.

## Requirements
| ID | Requirement |
|---|---|
| DOC-01 | `GET /documents/my/access` returns the documents the caller's department may access: id, title, source_url, status, allowed_departments. |
| DOC-02 | For admins, `/documents/my/access` returns all documents. |
| DOC-03 | Users without a department (non-admin) get 403 on `/my/access` and `/my/owned`. |
| DOC-04 | `GET /documents/my/{doc_id}/download` returns the PDF as `application/pdf` named `Document_{id}.pdf` if the caller's department has access or the caller is admin. |
| DOC-05 | Download returns 403 when the caller lacks access, 404 when the PDF file is missing on disk, 401 without a token. |
| DOC-06 | Department-access lists are cached in Redis (`docs:access:{dept_id}`, 15 min) and `docs:all` (10 min); results after a cache miss equal the DB state. |
| DOC-07 | `GET /documents/my/owned` returns documents owned by the caller's department. |

## Behavior / API
- Access is the many-to-many table `department_documents_access`; documents have no owner column yet (see gaps).
- PDFs are read from `backend/app/static/docs/{doc_id}.pdf`, written by ingestion.

## Files
`routers/docs.py`, `controllers/docs_controller.py`, `services/docs_service.py` (`list_documents_with_access`, `list_owned_documents`, `get_document_file_path`), `repositories/document_repository.py`, `models/document.py`, `models/department_documents_access.py`

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| DOC-01 | integration | Employee in dept A; docs shared with A and B | only docs shared with A listed |
| DOC-02 | integration | Admin calls `/my/access` | all docs |
| DOC-03 | integration | Employee with `department_id=None` | 403 |
| DOC-04 | integration | Allowed employee downloads existing PDF | 200, content-type pdf, filename header |
| DOC-05 | integration | Employee in dept without access | 403 |
| DOC-05 | integration | Allowed doc but file missing | 404 |
| DOC-05 | integration | No token | 401 |
| DOC-06 | unit | Second call with cache populated | DB not queried; after invalidation the DB is queried again |
| DOC-07 | integration | Docs with different owners | only caller dept's owned docs returned |

## Known gaps
- DOC-07: `DocumentRepository.get_documents_owned_by_department` filters on `Document.owner_department_id`, which does not exist on the model, so `/documents/my/owned` raises. Either add an owner column (and set it on create) or remove the endpoint.
- `get_document_file_path` mutates the JWT payload's `departments` list and treats the missing key as `[]`; only `department_id` is used in practice.
- Cache is only a hit when the cached list is non-empty (`if cached:`), so empty results are never cached.
- Download route uses `get_current_user` rather than `require_user_with_department` (same result for access check, different error for no-dept users).
- Docs are served from local disk only; a multi-instance deploy would need shared storage.

## Related docs
`admin-docs.md`, `ingestion.md`, `../frontend/my-documents.md`
