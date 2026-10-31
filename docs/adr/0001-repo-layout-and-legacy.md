# ADR 0001: Monorepo layout and handling of the legacy code

Status: accepted by the Owner (M0-01), within the approved OPEN-18 shape. Date: 2026-10-24.

## Decision
- Create the approved target layout next to the legacy folders: `apps/{frontend,api,worker}`, `packages/backend_core`, `infra/terraform`, `tests/`, `.github/workflows/`, root `pyproject.toml` (uv workspace) and `pnpm-workspace.yaml`.
- **Rebuild, do not move.** The legacy `backend/` (JWT, Celery/Redis, Chroma, gdown, sync SQLAlchemy, unsafe behaviors listed in `docs/reconciliation/legacy-conflicts.md` §2) and `frontend/` (plain JS, npm) conflict with the approved stack, so nothing is carried over by `git mv`. Their behavior is re-implemented from the specs in the milestone that owns it.
- `backend/` and `frontend/` stay in the tree, **untouched and excluded** from the workspaces, lint, type checks and CI, as read-only reference. They are not deployable (legacy-conflicts §2).
- **Committed binaries** (`backend/app/chroma_data/`, `backend/app/static/docs/*.pdf`) are **not removed** in M0 without the user's confirmation, because the PDFs may be wanted as sample corpus material (DEF-01). They are not copied into the target. Removing the legacy folders (history is preserved by git) is a separate, explicit commit once the user confirms.

## Consequences
- No legacy file is edited. The new tooling never reads `backend/` or `frontend/`.
- Until removal, the repository contains two stacks; `AGENTS.md` and the README state which is legacy.
