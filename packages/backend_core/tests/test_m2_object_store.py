"""M2-01 tests: ObjectStore implementations and the production guard (ARCH-14, Q6)."""

from pathlib import Path

import pytest

from knowserve_core.object_store import (
    ByteRange,
    FakeObjectStore,
    FilesystemObjectStore,
    ObjectNotFound,
    ObjectStore,
    build_object_store,
)

pytestmark = [pytest.mark.m2, pytest.mark.documents]

DATA = bytes(range(256)) * 600  # 153,600 bytes, spans several chunks


async def _collect(store: ObjectStore, key: str, byte_range: ByteRange | None = None) -> bytes:
    return b"".join([c async for c in store.stream(key, byte_range)])


@pytest.fixture(params=["fake", "filesystem"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> ObjectStore:
    if request.param == "fake":
        return FakeObjectStore()
    return FilesystemObjectStore(tmp_path)


async def test_put_size_and_full_stream(store: ObjectStore) -> None:
    await store.put("documents/a/b.pdf", DATA, "application/pdf")
    assert await store.size("documents/a/b.pdf") == len(DATA)
    assert await _collect(store, "documents/a/b.pdf") == DATA


async def test_byte_range_is_inclusive(store: ObjectStore) -> None:
    await store.put("k.pdf", DATA, "application/pdf")
    assert await _collect(store, "k.pdf", ByteRange(0, 0)) == DATA[:1]
    assert await _collect(store, "k.pdf", ByteRange(70000, 140000)) == DATA[70000:140001]
    assert ByteRange(5, 9).length == 5


async def test_missing_key_raises(store: ObjectStore) -> None:
    with pytest.raises(ObjectNotFound):
        await store.size("nope.pdf")
    with pytest.raises(ObjectNotFound):
        await _collect(store, "nope.pdf")


async def test_filesystem_store_rejects_path_escape(tmp_path: Path) -> None:
    (tmp_path.parent / "secret.txt").write_bytes(b"x")
    store = FilesystemObjectStore(tmp_path)
    with pytest.raises(ObjectNotFound):
        await store.size("../secret.txt")


def test_production_refuses_fake_and_filesystem(tmp_path: Path) -> None:
    for kind in ("fake", "filesystem"):
        with pytest.raises(ValueError, match="production"):
            build_object_store(kind, env="production", filesystem_root=tmp_path)


def test_local_factory_builds_both(tmp_path: Path) -> None:
    assert isinstance(build_object_store("fake", env="local"), FakeObjectStore)
    assert isinstance(
        build_object_store("filesystem", env="ci", filesystem_root=tmp_path), FilesystemObjectStore
    )
