"""Seed ingestion command (M3-02c, OPEN-28 Q8, OPEN-31 D4). LOCAL USE; production needs approval.

    python -m knowserve_worker.seed_ingest            # from the Worker environment
    python -m knowserve_api.seed.documents --ingest   # seed, then ingest (same code)

The four demo documents seeded in M2 are ``ready`` revisions with no chunks and no job. This
command gives each one a job and runs the same ``ingest_revision`` handler the Worker runs, in
reindex mode: chunks and the index identity are written; status, phase, page count, ready time,
the current pointer and every id stay as they are, and the document stays visible throughout. A
failure never fails a ready revision (the handler raises, the terminal hook skips ready rows).

Selection: a ``ready`` revision of a live document that has no chunks, unless its job is
processing under a live lease. So a seeded row, a failed run and a killed run are all picked up.
A second run after success changes nothing. The job is claimed and run in this process; no
message is sent to QStash, so the outbox row is created already ``published``.

Safety: it refuses to run with ``KS_ENV=production``, an R2 object store, or fake embeddings on a
non-local database unless ``--allow-production`` is given, which
only the Owner does after approving the production reindex (plan section 12.3, item 7). Output is
revision ids and outcome codes only: no text, no storage keys, no credentials.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import types
import uuid
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.db import create_engine, create_session_factory
from knowserve_core.embeddings import EmbeddingProvider
from knowserve_core.ingestion_contract import INGEST_JOB_TYPE, FailureCode
from knowserve_core.job_claims import claim_job, complete_job, fail_job
from knowserve_core.job_fencing import LostClaimError
from knowserve_core.job_hooks import NonRetryableJobError, RetryableJobError
from knowserve_core.jobs import enqueue_job
from knowserve_core.object_store import ObjectStore
from knowserve_core.revision_hooks import mark_revision_failed
from knowserve_core.settings import Settings, get_settings

from .app import JobContext, _build_embedding_provider, _build_object_store, _run_with_heartbeat
from .ingest import IngestHandler

logger = logging.getLogger("knowserve.worker.seed_ingest")
Factory = async_sessionmaker[AsyncSession]

_CANDIDATES = text(
    """
    SELECT r.id, r.job_id, j.status AS job_status, j.lease_expires_at AS job_lease,
           (j.lease_expires_at > now()) AS job_lease_live
    FROM document_revisions r
    JOIN documents d ON d.id = r.document_id
    LEFT JOIN jobs j ON j.id = r.job_id
    WHERE r.status = 'ready' AND d.deleted_at IS NULL
      AND NOT EXISTS (SELECT 1 FROM document_chunks c WHERE c.revision_id = r.id)
    ORDER BY r.created_at, r.id
    """
)
_LINK = text("UPDATE document_revisions SET job_id = :job_id WHERE id = :id")
_MARK_PUBLISHED = text(
    "UPDATE outbox SET status = 'published', published_at = now() WHERE job_id = :job_id"
)


@dataclass(frozen=True)
class SeedIngestResult:
    outcomes: dict[uuid.UUID, str]

    def counts(self) -> Counter[str]:
        return Counter(self.outcomes.values())

    @property
    def ok(self) -> bool:
        return not any(o.startswith("failed") for o in self.outcomes.values())


async def ingest_seeded(
    factory: Factory, store: ObjectStore, provider: EmbeddingProvider, settings: Settings
) -> SeedIngestResult:
    """Run the reindex for every selected revision, one at a time. Returns one outcome per
    candidate: ``ingested``, ``failed:<CODE>``, ``in_progress`` (a job holds a live lease) or
    ``lost``."""
    async with factory() as session:
        candidates = (await session.execute(_CANDIDATES)).all()
    handler = IngestHandler(factory, store, provider, settings)
    outcomes: dict[uuid.UUID, str] = {}
    for row in candidates:
        # Only a job that is processing under a live lease is in flight. Anything else (failed,
        # done without chunks, queued, or a killed run's expired lease) gets a new job.
        if row.job_id is not None and row.job_status == "processing" and row.job_lease_live:
            outcomes[row.id] = "in_progress"
            continue
        outcomes[row.id] = await _ingest_one(factory, handler, settings, row.id)
    return SeedIngestResult(outcomes)


async def _ingest_one(
    factory: Factory, handler: IngestHandler, settings: Settings, revision_id: uuid.UUID
) -> str:
    async with factory() as session, session.begin():
        job = await enqueue_job(session, INGEST_JOB_TYPE)
        await session.execute(_MARK_PUBLISHED, {"job_id": job.id})
        await session.execute(_LINK, {"job_id": job.id, "id": revision_id})
        job_id = job.id
    me = f"seed-ingest:{uuid.uuid4().hex[:8]}"
    claim = await claim_job(
        factory,
        job_id,
        me,
        lease_seconds=settings.job_lease_seconds,
        max_attempts=settings.job_max_attempts,
        terminal_hook=mark_revision_failed,
    )
    if claim.kind != "claimed" or claim.job is None:
        return "lost"
    ctx = JobContext(
        job_id,
        claim.job.job_type,
        claim.job.correlation_id,
        claim.job.attempts,
        claim.job.last_error,
        claimed_by=me,
        session_factory=factory,
    )
    state = types.SimpleNamespace(
        session_factory=factory, heartbeat_interval=max(0.05, settings.job_lease_seconds / 3)
    )
    code: FailureCode
    try:
        await _run_with_heartbeat(handler, ctx, state, settings)
    except LostClaimError:
        return "lost"
    except (NonRetryableJobError, RetryableJobError) as exc:
        code = exc.failure_code
    except Exception:
        code = FailureCode.INTERNAL_ERROR
    else:
        return "ingested" if await complete_job(factory, job_id, me) else "lost"
    # One attempt per run: the operator reruns after fixing the cause. The revision stays ready.
    await fail_job(factory, job_id, me, code, code.value, mark_revision_failed)
    return f"failed:{code.value}"


def guard(settings: Settings, argv: list[str]) -> str | None:
    """A refusal message, or None when it may run.

    ``--allow-production`` (Owner only) is needed when the environment is production, when the
    object store is R2, or when fake embeddings would be written into a non-local database.
    """
    reason = None
    if settings.env == "production":
        reason = "KS_ENV=production"
    elif settings.object_store == "r2":
        reason = "KS_OBJECT_STORE=r2"
    elif settings.embedding_provider == "fake" and not _local_database(settings.database_url):
        reason = "fake embeddings with a non-local database"
    if reason and "--allow-production" not in argv:
        return f"seed ingestion refused: {reason} needs --allow-production (Owner only)"
    return None


def _local_database(url: str) -> bool:
    return urlsplit(url).hostname in ("localhost", "127.0.0.1", "::1", "db")


async def ingest_from_env(argv: list[str] | None = None) -> int:
    """Run against the environment's database, object store and embedding provider."""
    args = sys.argv[1:] if argv is None else argv
    settings = get_settings()
    refusal = guard(settings, args)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    try:
        store = _build_object_store(settings)
        provider = _build_embedding_provider(settings)
    except (ValueError, RuntimeError) as exc:
        print(f"seed ingestion refused: {exc}", file=sys.stderr)
        return 2
    print(
        f"seed ingestion: embedding provider={settings.embedding_provider} "
        f"model={provider.model} object_store={settings.object_store}"
    )
    engine = create_engine(settings.database_url, null_pool=True)
    try:
        result = await ingest_seeded(create_session_factory(engine), store, provider, settings)
    finally:
        await engine.dispose()
    for revision_id, outcome in result.outcomes.items():
        print(f"{revision_id}: {outcome}")
    print("seed ingestion: " + ", ".join(f"{k}={v}" for k, v in sorted(result.counts().items())))
    return 0 if result.ok else 1


def main() -> None:
    sys.exit(asyncio.run(ingest_from_env()))


if __name__ == "__main__":
    main()
