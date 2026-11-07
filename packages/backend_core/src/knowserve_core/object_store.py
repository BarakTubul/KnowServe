"""Object storage interface for document bytes (ARCH-14, Q6).

Three implementations: ``FakeObjectStore`` (in memory, tests), ``FilesystemObjectStore`` (local
development) and ``R2ObjectStore`` (production, M2-03). No method returns a URL: bytes always pass
through the API (DOC-04). ``build_object_store`` refuses the fake and filesystem stores in
production, like the Firebase emulator guard.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

CHUNK_SIZE = 64 * 1024


class ObjectNotFound(Exception):
    """The key does not exist in the store."""


@dataclass(frozen=True)
class ByteRange:
    """Inclusive byte range, already validated against the object size."""

    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def size(self, key: str) -> int:
        """Size in bytes (head). Raises ``ObjectNotFound``."""
        ...

    def stream(self, key: str, byte_range: ByteRange | None = None) -> AsyncIterator[bytes]:
        """Yield the object, or only ``byte_range``, in chunks. Raises ``ObjectNotFound``."""
        ...


class FakeObjectStore:
    """In-memory store for automated tests."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._objects[key] = data

    async def size(self, key: str) -> int:
        try:
            return len(self._objects[key])
        except KeyError:
            raise ObjectNotFound(key) from None

    async def stream(self, key: str, byte_range: ByteRange | None = None) -> AsyncIterator[bytes]:
        try:
            data = self._objects[key]
        except KeyError:
            raise ObjectNotFound(key) from None
        if byte_range is not None:
            data = data[byte_range.start : byte_range.end + 1]
        for i in range(0, len(data), CHUNK_SIZE):
            yield data[i : i + CHUNK_SIZE]


class FilesystemObjectStore:
    """Local development store rooted at a directory. Keys cannot escape the root."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if self._root != path and self._root not in path.parents:
            raise ObjectNotFound(key)
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def size(self, key: str) -> int:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path.stat().st_size

    async def stream(self, key: str, byte_range: ByteRange | None = None) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        with path.open("rb") as handle:
            remaining: int | None = None
            if byte_range is not None:
                handle.seek(byte_range.start)
                remaining = byte_range.length
            while remaining is None or remaining > 0:
                chunk = handle.read(CHUNK_SIZE if remaining is None else min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                if remaining is not None:
                    remaining -= len(chunk)
                yield chunk


def build_object_store(kind: str, *, env: str, filesystem_root: Path | None = None) -> ObjectStore:
    """Select a store. The fake and filesystem stores are refused when ``env`` is production."""
    if kind == "r2":
        # Implemented by M2-03 (R2ObjectStore over the S3 API).
        raise NotImplementedError("R2ObjectStore arrives with M2-03")
    if env == "production":
        raise ValueError(f"KS_OBJECT_STORE={kind!r} is not allowed when KS_ENV=production")
    if kind == "filesystem":
        if filesystem_root is None:
            raise ValueError("KS_OBJECT_STORE_PATH is required for the filesystem store")
        return FilesystemObjectStore(filesystem_root)
    if kind == "fake":
        return FakeObjectStore()
    raise ValueError(f"Unknown KS_OBJECT_STORE {kind!r}")
