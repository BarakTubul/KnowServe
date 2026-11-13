"""Idempotent demo document seed (M2-05, D1, Q5).

    python -m knowserve_api.seed.documents [--ingest]

``--ingest`` (M3-02c) then indexes the seeded revisions through the Worker's ingest handler in
reindex mode (``knowserve_worker.seed_ingest``). It needs the Worker package and its settings.

Reads ``KS_DATABASE_URL``, ``KS_ENV`` (default ``local``), ``KS_OBJECT_STORE`` (default
``filesystem``) and ``KS_OBJECT_STORE_PATH``; for ``r2`` it also reads ``KS_R2_ENDPOINT``,
``KS_R2_BUCKET``, ``KS_R2_ACCESS_KEY_ID`` and ``KS_R2_SECRET_ACCESS_KEY``. Nothing else, so it runs
in a job without the API, proxy or QStash settings.

It refuses to run (exit 2, nothing written) until migration ``0003`` has created the document
tables, so the production job cannot seed ahead of the migration.

Safety rules:

* Ids are uuid5 (fixed namespace plus slug), so a rerun finds the same rows.
* A document that already exists is left untouched: no row is updated and no access row is added or
  removed. Editing access of an existing seed document is a deliberate manual act, not a rerun.
* An object that already exists is never overwritten. If its size differs from the committed file
  the run reports ``object_conflict`` and exits non-zero.
* Revisions are inserted ``ready`` with a page count, no chunks and no jobs (M3 owns indexing, Q8).
* The object is written before its rows, so a failure leaves at worst an unreferenced object that
  the next run reuses.
* Output is counts and slugs only: no credentials, urls or storage keys.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from knowserve_core.db import create_engine, create_session_factory
from knowserve_core.models import Department, Document, DocumentDepartmentAccess, DocumentRevision
from knowserve_core.object_store import ObjectNotFound, ObjectStore, R2Config, build_object_store
from knowserve_core.settings import normalize_database_url

from .specs import SEED_DOCUMENTS, SeedDocument

DATA_DIR = Path(__file__).parent / "data"
CONTENT_TYPE = "application/pdf"

Outcome = Literal["created", "unchanged", "object_conflict", "incomplete"]


class SeedError(Exception):
    """The seed cannot continue (bad committed file, missing department)."""


_COUNT = re.compile(rb"/Type /Pages[^>]*?/Count (\d+)")


def pdf_page_count(data: bytes) -> int:
    match = _COUNT.search(data)
    if not data.startswith(b"%PDF-") or match is None:
        raise SeedError("The seed file is not a PDF this seed can count")
    return int(match.group(1))


async def _ensure_object(store: ObjectStore, spec: SeedDocument, data: bytes) -> bool:
    """Write the object only if absent. Return False when a different object is already there."""
    try:
        existing = await store.size(spec.storage_key)
    except ObjectNotFound:
        await store.put(spec.storage_key, data, CONTENT_TYPE)
        return True
    return existing == len(data)


async def _department_ids(session: AsyncSession) -> dict[str, uuid.UUID]:
    rows = await session.execute(select(Department.slug, Department.id))
    return {slug: dept_id for slug, dept_id in rows.all()}


async def _seed_one(
    factory: async_sessionmaker[AsyncSession],
    store: ObjectStore,
    spec: SeedDocument,
    data_dir: Path,
) -> Outcome:
    data = (data_dir / spec.filename).read_bytes()
    pages = pdf_page_count(data)
    if pages != spec.pages:
        raise SeedError(f"Page count of {spec.slug} does not match its spec")
    object_ok = await _ensure_object(store, spec, data)
    if not object_ok:
        return "object_conflict"
    async with factory() as db, db.begin():
        departments = await _department_ids(db)
        missing = {spec.owner, *spec.allowed} - departments.keys()
        if missing:
            raise SeedError(f"Unknown department slug(s) for {spec.slug}")
        now = datetime.now(UTC)
        inserted = await db.execute(
            insert(Document)
            .values(
                id=spec.document_id,
                title=spec.title,
                filename=spec.filename,
                owner_department_id=departments[spec.owner],
            )
            .on_conflict_do_nothing(index_elements=[Document.id])
        )
        if inserted.rowcount == 0:  # type: ignore[attr-defined]
            # The row exists. Say "unchanged" only if it is the complete seed shape; a partial
            # row (created outside this command) is reported, never repaired or called success.
            current = await db.scalar(
                select(Document.current_revision_id).where(Document.id == spec.document_id)
            )
            granted = set(
                (
                    await db.scalars(
                        select(DocumentDepartmentAccess.department_id).where(
                            DocumentDepartmentAccess.document_id == spec.document_id
                        )
                    )
                ).all()
            )
            complete = current == spec.revision_id and granted == {
                departments[slug] for slug in spec.allowed
            }
            return "unchanged" if complete else "incomplete"
        db.add(
            DocumentRevision(
                id=spec.revision_id,
                document_id=spec.document_id,
                storage_key=spec.storage_key,
                status="ready",
                page_count=pages,
                size_bytes=len(data),
                content_type=CONTENT_TYPE,
                ready_at=now,
            )
        )
        for slug in spec.allowed:
            db.add(
                DocumentDepartmentAccess(
                    document_id=spec.document_id, department_id=departments[slug]
                )
            )
        await db.flush()
        await db.execute(
            update(Document)
            .where(Document.id == spec.document_id)
            .values(current_revision_id=spec.revision_id)
        )
    return "created"


async def seed_documents(
    factory: async_sessionmaker[AsyncSession],
    store: ObjectStore,
    *,
    specs: Sequence[SeedDocument] = SEED_DOCUMENTS,
    data_dir: Path = DATA_DIR,
) -> dict[str, Outcome]:
    """Seed every spec; return the outcome per slug."""
    return {spec.slug: await _seed_one(factory, store, spec, data_dir) for spec in specs}


def r2_config_from_env() -> R2Config:
    """The R2 settings from the job's environment. Values are never printed."""
    return R2Config(
        endpoint=os.environ.get("KS_R2_ENDPOINT") or None,
        bucket=os.environ.get("KS_R2_BUCKET") or None,
        access_key_id=os.environ.get("KS_R2_ACCESS_KEY_ID") or None,
        secret_access_key=os.environ.get("KS_R2_SECRET_ACCESS_KEY") or None,
    )


async def schema_ready(engine: AsyncEngine) -> bool:
    """True once migration 0003 has created all three document tables."""
    async with engine.connect() as conn:
        found = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename IN "
                "('documents', 'document_revisions', 'document_department_access')"
            )
        )
    return found == 3


async def _run() -> int:
    url = os.environ.get("KS_DATABASE_URL")
    if not url:
        print("KS_DATABASE_URL must be set", file=sys.stderr)
        return 2
    kind = os.environ.get("KS_OBJECT_STORE", "filesystem")
    env = os.environ.get("KS_ENV", "local")
    root = os.environ.get("KS_OBJECT_STORE_PATH", ".local/objects")
    try:
        store = build_object_store(
            kind, env=env, filesystem_root=Path(root), r2=r2_config_from_env()
        )
    except (ValueError, NotImplementedError) as exc:
        print(f"document seed refused: {exc}", file=sys.stderr)
        return 2
    engine = create_engine(normalize_database_url(url), null_pool=True)
    try:
        if not await schema_ready(engine):
            print("document seed refused: migration 0003 has not run", file=sys.stderr)
            return 2
        outcomes = await seed_documents(create_session_factory(engine), store)
    except SeedError as exc:
        print(f"document seed refused: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()
    for slug, outcome in outcomes.items():
        print(f"{slug}: {outcome}")
    counts = Counter(outcomes.values())
    print("document seed: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    code = 1 if counts["object_conflict"] or counts["incomplete"] else 0
    if "--ingest" in sys.argv[1:]:
        # M3-02c (Q8): index the seeded revisions through the Worker's handler in reindex mode.
        try:
            from knowserve_worker.seed_ingest import ingest_from_env
        except ImportError:
            print(
                "document seed: --ingest needs the Worker package (run it from its image)",
                file=sys.stderr,
            )
            return 2
        code = max(code, await ingest_from_env())
    return code


def main() -> None:
    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
