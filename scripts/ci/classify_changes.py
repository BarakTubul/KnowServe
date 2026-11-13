"""Decide whether a pull request changes only documentation (OPEN-22).

Reads NUL-separated changed paths on stdin (``git diff --name-only --no-renames -z``) and prints
``docs_only=true`` or ``docs_only=false``. Anything unexpected gives ``false``, so the full CI
runs. Standard library only: the ``changes`` job runs it without installing dependencies.

Docs-only means every path is ``docs/**/*.md`` or one of the root files in ROOT_DOCS.
Everything else (``docs/contracts/openapi.json``, ``.github/``, code, config) is not docs-only.
"""

from __future__ import annotations

import sys

ROOT_DOCS = frozenset({"README.md", "AGENTS.md", "CLAUDE.md"})


def is_docs_path(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path:
        return False
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if path in ROOT_DOCS:
        return True
    return parts[0] == "docs" and len(parts) > 1 and path.endswith(".md")


def is_docs_only(paths: list[str]) -> bool:
    return bool(paths) and all(is_docs_path(p) for p in paths)


def main() -> int:
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    paths = [p for p in raw.split("\0") if p]
    print(f"docs_only={'true' if is_docs_only(paths) else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
