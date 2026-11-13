"""OPEN-22: the docs-only classifier fails closed (TEST-10, TEST-13)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "classify_changes",
    Path(__file__).resolve().parents[2] / "scripts" / "ci" / "classify_changes.py",
)
assert _SPEC and _SPEC.loader
classify = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(classify)


@pytest.mark.parametrize(
    "paths",
    [
        ["docs/architecture/ci-cd-proposals.md"],
        ["docs/open-decisions.md", "README.md", "AGENTS.md", "CLAUDE.md"],
    ],
)
def test_open22_docs_only_paths_are_docs_only(paths: list[str]) -> None:
    assert classify.is_docs_only(paths)


@pytest.mark.parametrize(
    "paths",
    [
        [],
        ["docs/contracts/openapi.json"],
        ["docs/notes.txt"],
        ["docs"],
        ["docs/.md/../../apps/api/x.md"],
        [".github/workflows/ci.yml"],
        [".github/CODEOWNERS"],
        ["scripts/ci/classify_changes.py"],
        ["infra/README.md"],
        ["apps/frontend/README.md"],
        ["README.md.py"],
        ["sub/README.md"],
        ["/docs/a.md"],
        ["docs\a.md"],
        ["docs/a.md", "apps/api/src/knowserve_api/app.py"],
    ],
)
def test_open22_anything_else_is_not_docs_only(paths: list[str]) -> None:
    assert not classify.is_docs_only(paths)
