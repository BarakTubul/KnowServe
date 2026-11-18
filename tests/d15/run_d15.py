"""D15 runner: the controlled production failure and recovery experiment (M3-AC25, plan 12.2).

OWNER ONLY. It writes job rows to the database in ``KS_DATABASE_URL`` and publishes real QStash
messages, so it never runs without the Owner's approval of the exact steps. The steps, the tagged
Worker revision it needs and the removal are in ``docs/milestones/M3/d15-runbook.md``. This script
is not part of any image.

What it does, and what it never does:

* It creates at most four experiment jobs of the test types ``noop``, ``always_fail`` and
  ``fail_then_ok`` (correlation id prefix ``d15-``). No document, revision, chunk, R2 object or
  OpenAI call is involved. It checks that the document table counts did not change.
* It publishes to the tagged Worker URL (``https://d15---...a.run.app``) only. Any other
  destination is refused, so the serving revision can never receive an experiment job.
* It prints one line per change: the job row (status, attempts, delivery state, last error) and
  every QStash delivery event (time, state, HTTP status, next delivery time).

Scenarios (run one at a time):

* ``cycle``      ``fail_then_ok``: 4 failed deliveries, the job ends ``failed``, a manual retry
                 publishes a new message and the job ends ``done``. Covers the redelivery after a
                 non-2xx answer (the first retry is the "transient failure" observation), the cap
                 of 4 attempts, no delivery after the fourth, and manual retry after the cap.
                 About 33 minutes at the default QStash delays.
* ``cap``        ``always_fail``: 4 claims, the job ends ``failed``, nothing more is delivered.
* ``duplicate``  ``noop`` published twice at once: one claim, one result.

Other commands: ``watch JOB_ID [MESSAGE_ID ...]`` resumes watching, ``cancel MESSAGE_ID ...``
cancels pending QStash messages, ``dry-run`` checks the configuration and writes nothing.

Environment (never printed): ``KS_DATABASE_URL`` (the runtime role is enough), ``KS_QSTASH_TOKEN``,
``KS_QSTASH_URL`` (default: the EU endpoint), ``KS_D15_TAG_URL`` (or ``--tag-url``).
Run from the repository root:
``uv run python tests/d15/run_d15.py cycle --i-have-the-owners-approval``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from knowserve_core.db import create_engine, create_session_factory
from knowserve_core.job_recovery import JobView, create_job, get_job_view, retry_job
from knowserve_core.qstash import CORRELATION_HEADER, PublishError, build_envelope
from knowserve_core.settings import normalize_database_url

PROD_TAG_URL = re.compile(r"^https://d15---[a-z0-9.-]+\.run\.app$")
LOCAL_URL = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d+)?$")
DEFAULT_QSTASH_URL = "https://qstash-eu-central-1.upstash.io"
GRACE_SECONDS = 120  # application defaults (settings.py); only used to label the delivery state
STUCK_SECONDS = 2400
MAX_JOBS = 4
POLL_SECONDS = 5.0
Factory = async_sessionmaker[AsyncSession]


def stamp() -> str:
    return datetime.now(UTC).strftime("%H:%M:%S")


def say(message: str) -> None:
    print(f"{stamp()}  {message}", flush=True)


class D15Publisher:
    """Publishes the job envelope to the tagged Worker only and remembers each message id."""

    def __init__(
        self, qstash_url: str, token: str, tag_url: str, retry_delay_ms: int | None
    ) -> None:
        self._base = qstash_url.rstrip("/")
        self._token = token
        self._destination = tag_url.rstrip("/") + "/internal/jobs/run"
        self._retry_delay_ms = retry_delay_ms
        self.message_ids: dict[str, list[str]] = {}

    async def publish(self, job_id: uuid.UUID, correlation_id: str) -> None:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            f"Upstash-Forward-{CORRELATION_HEADER}": correlation_id,
        }
        if self._retry_delay_ms is not None:
            headers["Upstash-Retry-Delay"] = str(self._retry_delay_ms)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self._base}/v2/publish/{self._destination}",
                    headers=headers,
                    json=build_envelope(job_id),
                )
        except httpx.HTTPError as exc:
            raise PublishError(f"QStash request failed: {type(exc).__name__}") from None
        if response.status_code >= 300:
            raise PublishError(f"QStash rejected the publish with status {response.status_code}")
        try:
            message_id = str(response.json().get("messageId", ""))
        except ValueError:
            message_id = ""
        if message_id:
            self.message_ids.setdefault(str(job_id), []).append(message_id)
            say(f"published job {job_id} as QStash message {message_id}")


class Events:
    """Reads delivery events from the QStash API. Failures only print one warning."""

    def __init__(self, qstash_url: str, token: str, enabled: bool) -> None:
        self._base = qstash_url.rstrip("/")
        self._token = token
        self._enabled = enabled
        self._warned = False
        self._seen: set[str] = set()

    async def poll(self, message_ids: list[str]) -> None:
        if not self._enabled:
            return
        for message_id in message_ids:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.get(
                        f"{self._base}/v2/events",
                        params={"messageId": message_id},
                        headers={"Authorization": f"Bearer {self._token}"},
                    )
                response.raise_for_status()
                events = response.json().get("events", [])
            except (httpx.HTTPError, ValueError) as exc:
                if not self._warned:
                    say(
                        f"warning: QStash events are unavailable ({type(exc).__name__}); "
                        "use the Cloud Run request logs for the delivery list"
                    )
                    self._warned = True
                return
            for event in sorted(events, key=lambda e: e.get("time", 0)):
                key = json.dumps(
                    [message_id, event.get("time"), event.get("state"), event.get("responseStatus")]
                )
                if key in self._seen:
                    continue
                self._seen.add(key)
                when = event.get("time")
                at = (
                    datetime.fromtimestamp(when / 1000, UTC).strftime("%H:%M:%S")
                    if isinstance(when, int | float)
                    else "?"
                )
                nxt = event.get("nextDeliveryTime")
                nxt_text = (
                    datetime.fromtimestamp(nxt / 1000, UTC).strftime("%H:%M:%S")
                    if isinstance(nxt, int | float)
                    else "-"
                )
                say(
                    f"  qstash {message_id[:12]} event@{at} state={event.get('state')} "
                    f"http={event.get('responseStatus', '-')} next={nxt_text}"
                )


async def counts(factory: Factory) -> dict[str, int]:
    """Row counts that must not change: the experiment touches no document data."""
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM documents), "
                    "(SELECT count(*) FROM document_revisions), "
                    "(SELECT count(*) FROM document_chunks)"
                )
            )
        ).one()
    return {"documents": row[0], "document_revisions": row[1], "document_chunks": row[2]}


async def view(factory: Factory, job_id: uuid.UUID) -> JobView:
    found = await get_job_view(
        factory, job_id, grace_seconds=GRACE_SECONDS, stuck_after_seconds=STUCK_SECONDS
    )
    if found is None:
        raise SystemExit(f"job {job_id} not found")
    return found


async def watch(
    factory: Factory,
    events: Events,
    job_id: uuid.UUID,
    message_ids: list[str],
    done: Callable[[JobView], bool],
    timeout_seconds: float,
) -> JobView:
    started = time.monotonic()
    last: tuple[object, ...] | None = None
    while True:
        current = await view(factory, job_id)
        row = (current.job_status, current.attempts, current.delivery_state, current.last_error)
        if row != last:
            say(
                f"job {str(job_id)[:8]} status={current.job_status} attempts={current.attempts} "
                f"delivery={current.delivery_state} last_error={current.last_error!r}"
            )
            last = row
        await events.poll(message_ids)
        if done(current):
            return current
        if time.monotonic() - started > timeout_seconds:
            raise SystemExit("timed out waiting; the experiment is not finished (see the runbook)")
        await asyncio.sleep(POLL_SECONDS)


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        self.rows.append((label, ok, detail))
        say(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))

    def finish(self) -> int:
        failed = [label for label, ok, _ in self.rows if not ok]
        print()
        print("ALL CHECKS PASSED" if not failed else f"{len(failed)} CHECK(S) FAILED")
        return 0 if not failed else 1


class Context:
    def __init__(self, args: argparse.Namespace, factory: Factory, publisher: D15Publisher) -> None:
        self.args = args
        self.factory = factory
        self.publisher = publisher
        self.events = Events(args.qstash_url, args.qstash_token, not args.no_events)
        self.state_path = Path(args.state_file)

    def remember(self, scenario: str, job_id: uuid.UUID) -> None:
        state: dict[str, Any] = {}
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state[str(job_id)] = {
            "scenario": scenario,
            "messages": self.publisher.message_ids.get(str(job_id), []),
            "at": datetime.now(UTC).isoformat(),
        }
        self.state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")

    async def new_job(self, job_type: str, publish: bool = True) -> uuid.UUID:
        job_id = await create_job(
            self.factory,
            self.publisher,
            job_type,
            correlation_id=f"d15-{uuid.uuid4().hex[:12]}",
            publish=publish,
            publish_timeout=15.0,
        )
        say(f"created {job_type} job {job_id}")
        return job_id


async def run_failing(ctx: Context, job_type: str, with_manual_retry: bool) -> int:
    report = Report()
    before = await counts(ctx.factory)
    job_id = await ctx.new_job(job_type)
    ctx.remember(job_type, job_id)
    first = list(ctx.publisher.message_ids.get(str(job_id), []))

    final = await watch(
        ctx.factory,
        ctx.events,
        job_id,
        first,
        lambda v: v.job_status == "failed" and v.attempts >= 4,
        ctx.args.timeout_minutes * 60,
    )
    report.check(
        "the job reached 4 processing attempts and ended failed",
        final.attempts == 4 and final.job_status == "failed",
        f"attempts={final.attempts} status={final.job_status}",
    )

    say(f"waiting {ctx.args.settle_seconds}s to confirm no delivery follows the fourth")
    await asyncio.sleep(ctx.args.settle_seconds)
    await ctx.events.poll(first)
    settled = await view(ctx.factory, job_id)
    report.check(
        "no further attempt after the cap", settled.attempts == 4, f"attempts={settled.attempts}"
    )

    if with_manual_retry:
        say("manual retry of the failed job (a new QStash message)")
        result = await retry_job(
            ctx.factory,
            ctx.publisher,
            job_id,
            grace_seconds=GRACE_SECONDS,
            stuck_after_seconds=STUCK_SECONDS,
            publish_timeout=15.0,
        )
        say(f"retry action={result.action} published={result.published}")
        ctx.remember(job_type, job_id)
        second = [m for m in ctx.publisher.message_ids.get(str(job_id), []) if m not in first]
        report.check("the manual retry published a new message", bool(second) and result.published)
        done = await watch(
            ctx.factory,
            ctx.events,
            job_id,
            first + second,
            lambda v: v.job_status == "done",
            ctx.args.timeout_minutes * 60,
        )
        report.check(
            "the job ended done after the manual retry",
            done.job_status == "done",
            f"attempts={done.attempts}",
        )
        report.check(
            "attempts restarted for the new run", done.attempts == 1, f"attempts={done.attempts}"
        )

    after = await counts(ctx.factory)
    report.check("no document, revision or chunk row changed", before == after, str(after))
    return report.finish()


async def run_duplicate(ctx: Context) -> int:
    report = Report()
    before = await counts(ctx.factory)
    job_id = await ctx.new_job("noop", publish=False)
    say("publishing the same job twice at once")
    correlation = f"d15-{uuid.uuid4().hex[:12]}"
    await asyncio.gather(
        ctx.publisher.publish(job_id, correlation), ctx.publisher.publish(job_id, correlation)
    )
    ctx.remember("duplicate", job_id)
    messages = ctx.publisher.message_ids.get(str(job_id), [])
    report.check("two messages were published", len(messages) == 2, str(len(messages)))
    final = await watch(
        ctx.factory, ctx.events, job_id, messages, lambda v: v.job_status == "done", 300
    )
    await asyncio.sleep(ctx.args.settle_seconds)
    await ctx.events.poll(messages)
    settled = await view(ctx.factory, job_id)
    report.check(
        "one claim produced one result",
        settled.attempts == 1 and settled.job_status == "done",
        f"attempts={settled.attempts} status={final.job_status}",
    )
    after = await counts(ctx.factory)
    report.check("no document, revision or chunk row changed", before == after, str(after))
    print(
        "Read the second delivery's HTTP status in the events above or the Cloud Run request "
        "log: 409 (claim refused) or 200 (job already done) are both correct."
    )
    return report.finish()


def check_environment(args: argparse.Namespace) -> list[str]:
    problems: list[str] = []
    if not args.database_url:
        problems.append("KS_DATABASE_URL is not set")
    if not args.qstash_token:
        problems.append("KS_QSTASH_TOKEN is not set")
    tag = args.tag_url or ""
    if args.local_test:
        if not LOCAL_URL.match(tag):
            problems.append("--local-test accepts only http://localhost or http://127.0.0.1")
    elif not PROD_TAG_URL.match(tag):
        problems.append(
            "the tag URL must look like https://d15---<service>-<id>.<...>.run.app "
            "(the serving URL is refused on purpose)"
        )
    return problems


async def main_async(args: argparse.Namespace) -> int:
    problems = check_environment(args)
    if problems:
        for problem in problems:
            print(f"refused: {problem}", file=sys.stderr)
        return 2
    if args.command == "dry-run":
        print("configuration looks right; nothing was written")
        return 0
    if args.command == "cancel":
        for message_id in args.ids:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.delete(
                    f"{args.qstash_url.rstrip('/')}/v2/messages/{message_id}",
                    headers={"Authorization": f"Bearer {args.qstash_token}"},
                )
            say(f"cancel {message_id}: HTTP {response.status_code}")
        return 0
    if not args.i_have_the_owners_approval:
        print(
            "refused: pass --i-have-the-owners-approval only after the Owner approved this run",
            file=sys.stderr,
        )
        return 2

    engine = create_engine(normalize_database_url(args.database_url), null_pool=True)
    factory = create_session_factory(engine)
    publisher = D15Publisher(
        args.qstash_url,
        args.qstash_token,
        args.tag_url,
        args.retry_delay_ms,
    )
    ctx = Context(args, factory, publisher)
    try:
        if args.command == "cycle":
            return await run_failing(ctx, "fail_then_ok", with_manual_retry=True)
        if args.command == "cap":
            return await run_failing(ctx, "always_fail", with_manual_retry=False)
        if args.command == "duplicate":
            return await run_duplicate(ctx)
        if args.command == "watch":
            ids = [str(i) for i in args.ids]
            job_id = uuid.UUID(args.job_id)
            await watch(
                factory,
                ctx.events,
                job_id,
                ids,
                lambda v: v.job_status in ("done", "failed"),
                args.timeout_minutes * 60,
            )
            return 0
        raise SystemExit(f"unknown command {args.command}")
    finally:
        await engine.dispose()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="D15 failure and recovery experiment (Owner only)")
    p.add_argument("command", choices=["cycle", "cap", "duplicate", "watch", "cancel", "dry-run"])
    p.add_argument("ids", nargs="*", help="watch: message ids; cancel: message ids")
    p.add_argument("--job-id", help="watch: the job id")
    p.add_argument("--tag-url", default=os.environ.get("KS_D15_TAG_URL"))
    p.add_argument(
        "--retry-delay-ms",
        type=int,
        default=None,
        help="shorten QStash's retry delay (the real delays are then not observed)",
    )
    p.add_argument("--timeout-minutes", type=int, default=50)
    p.add_argument("--settle-seconds", type=int, default=90)
    p.add_argument("--no-events", action="store_true", help="skip the QStash events API")
    p.add_argument(
        "--local-test",
        action="store_true",
        help="allow a localhost destination (the local stack only, never production)",
    )
    p.add_argument("--state-file", default=str(Path(tempfile.gettempdir()) / "d15-state.json"))
    p.add_argument("--i-have-the-owners-approval", action="store_true")
    return p


def main() -> None:
    args = parser().parse_args()
    args.database_url = os.environ.get("KS_DATABASE_URL", "")
    args.qstash_token = os.environ.get("KS_QSTASH_TOKEN", "")
    args.qstash_url = os.environ.get("KS_QSTASH_URL", DEFAULT_QSTASH_URL)
    if args.command == "watch":
        args.ids = args.ids or []
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
