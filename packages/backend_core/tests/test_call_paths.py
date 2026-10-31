"""M0-AC10 / M0-AC16: no active M0 path can run the multi-row batch dispatcher.

``dispatch_pending`` is the only function that claims more than one outbox row, and its batch
lease-expiry gap is deferred (docs/contracts/jobs-outbox.md). This test proves by static call-path
analysis that nothing but the optional, flag-gated Worker route calls it, and that the immediate
and manual paths use the single-row claims.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCES = [*ROOT.glob("apps/*/src/**/*.py"), *ROOT.glob("packages/*/src/**/*.py")]


def _calls(tree: ast.AST) -> list[tuple[str, int]]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
            found.append((name, node.lineno))
    return found


def _references(name: str) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = [
            n
            for n in ast.walk(tree)
            if (isinstance(n, ast.Name) and n.id == name)
            or (isinstance(n, ast.Attribute) and n.attr == name)
            or (isinstance(n, ast.alias) and n.name == name)
            or (isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == name)
        ]
        if hits:
            refs[str(path.relative_to(ROOT)).replace("\\", "/")] = [str(h.lineno) for h in hits]
    return refs


@pytest.mark.m0
def test_m0_ac10_only_the_optional_worker_route_references_the_batch_dispatcher() -> None:
    refs = _references("dispatch_pending")
    assert set(refs) == {
        "packages/backend_core/src/knowserve_core/outbox.py",  # definition
        "apps/worker/src/knowserve_worker/app.py",  # import + the one call
    }
    worker = (ROOT / "apps/worker/src/knowserve_worker/app.py").read_text(encoding="utf-8")
    tree = ast.parse(worker)
    callers = [
        fn.name
        for fn in ast.walk(tree)
        if isinstance(fn, ast.AsyncFunctionDef)
        and any(name == "dispatch_pending" for name, _ in _calls(fn))
    ]
    assert callers == ["dispatch"]
    # That function is registered on the router that is mounted only behind the flag.
    assert '@dispatcher_router.post("/internal/outbox/dispatch"' in worker
    assert (
        "if settings.enable_recovery_dispatcher:\n        app.include_router(dispatcher_router)"
        in worker
    )


@pytest.mark.m0
def test_m0_ac10_immediate_and_manual_paths_use_single_row_claims_only() -> None:
    outbox = ast.parse(
        (ROOT / "packages/backend_core/src/knowserve_core/outbox.py").read_text("utf-8")
    )
    uses: dict[str, set[str]] = {}
    for fn in ast.walk(outbox):
        if isinstance(fn, ast.AsyncFunctionDef):
            uses[fn.name] = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "_CLAIM_BATCH" in uses["dispatch_pending"]
    for single in ("publish_after_commit", "republish_manual"):
        assert "_CLAIM_BATCH" not in uses[single] and "dispatch_pending" not in uses[single]
    recovery = (ROOT / "packages/backend_core/src/knowserve_core/job_recovery.py").read_text(
        "utf-8"
    )
    api = (ROOT / "apps/api/src/knowserve_api/operator.py").read_text("utf-8")
    assert "dispatch_pending" not in recovery and "dispatch_pending" not in api
    assert "_CLAIM_BATCH" not in recovery and "_CLAIM_BATCH" not in api
