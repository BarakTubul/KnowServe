"""ZIP and manifest validation for the import (M3-04, ADM-11, ADM-12, SEC-11).

The archive is read in memory and never extracted to disk. ``inspect_zip`` is synchronous and
CPU-bound; callers run it in a thread. Two kinds of problem:

* Archive-level (unsafe path, symlink, bomb, too many files, nested or encrypted entries,
  duplicate names, a file the manifest does not list, a bad manifest): the whole request is
  rejected with an ``AppError`` and nothing is read further.
* Entry-level (title, departments, a listed file that is missing or not a PDF): that entry is
  marked invalid with its code and the others proceed, so a partial import is possible (ADM-14).

Decompression is bounded by the declared sizes, which are checked against the limits first;
``zipfile`` stops reading at the declared size and verifies the CRC, so a header that lies about
its size fails instead of expanding.
"""

from __future__ import annotations

import io
import json
import re
import stat
import unicodedata
import zipfile
from dataclasses import dataclass, field
from typing import Any

from knowserve_core.ingestion_contract import (
    ADMIN_ERRORS,
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    AdminErrorCode,
)
from knowserve_core.settings import Settings
from knowserve_core.web import AppError

from ..schemas import DepartmentOut
from .validation import (
    _BIDI_FORMATTING,
    _BIDI_MARKS,
    PdfCheck,
    check_pdf_structure,
    reject,
    validate_pdf,
    validate_title,
)

_EOCD = b"PK\x05\x06"
_EOCD_SEARCH = 65_557
_CD_ALLOWANCE = 4096  # central directory bytes allowed per entry (name, extra field, comment)
_ENTRY_SLACK = 64  # directory entries and the manifest on top of the file limit
_ARCHIVE_SUFFIXES = (".zip", ".jar", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".war")
_ALLOWED_METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
_ENTRY_KEYS = frozenset({"file", "title", "owner_department", "allowed_departments"})
_DRIVE = re.compile(r"^[A-Za-z]:")


@dataclass
class EntryPlan:
    index: int
    file: str
    title: str | None = None
    owner: DepartmentOut | None = None
    allowed: list[DepartmentOut] = field(default_factory=list)
    error_code: AdminErrorCode | None = None
    detail: str | None = None

    @property
    def valid(self) -> bool:
        return self.error_code is None

    @property
    def error_message(self) -> str | None:
        return ADMIN_ERRORS[self.error_code].message if self.error_code else None


def _fail(code: AdminErrorCode) -> AppError:
    return reject(code)


def _unsafe_path(name: str) -> bool:
    if not name or len(name) > 255 or "\\" in name or name.startswith("/") or _DRIVE.match(name):
        return True
    for ch in name:
        if (
            unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp")
            or ch in _BIDI_FORMATTING
            or ch in _BIDI_MARKS
        ):
            return True
    return any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))


def _check_directory_size(data: bytes, settings: Settings) -> None:
    """Bound the central directory before ``zipfile`` builds an object per entry."""
    at = data.rfind(_EOCD, max(0, len(data) - _EOCD_SEARCH))
    if at == -1 or len(data) < at + 22:
        raise _fail(AdminErrorCode.ZIP_INVALID)
    total = int.from_bytes(data[at + 10 : at + 12], "little")
    cd_size = int.from_bytes(data[at + 12 : at + 16], "little")
    limit = settings.upload_max_zip_files + _ENTRY_SLACK
    if total > limit or cd_size > limit * _CD_ALLOWANCE:
        raise _fail(AdminErrorCode.ZIP_TOO_MANY_FILES)


def _open(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError, NotImplementedError, EOFError):
        raise _fail(AdminErrorCode.ZIP_INVALID) from None


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    try:
        return archive.read(info)
    except (zipfile.BadZipFile, RuntimeError, ValueError, OSError, NotImplementedError, EOFError):
        raise _fail(AdminErrorCode.ZIP_INVALID) from None


def _validate_members(archive: zipfile.ZipFile, settings: Settings) -> dict[str, zipfile.ZipInfo]:
    """Archive-level checks on the headers only. Returns the file members by exact name."""
    members: dict[str, zipfile.ZipInfo] = {}
    seen: set[str] = set()
    total = 0
    for info in archive.infolist():
        name = info.filename
        # ``orig_filename`` is the name as stored; on Windows ``zipfile`` rewrites backslashes in
        # ``filename``, so check both and the result is the same on every platform.
        if _unsafe_path(name) or _unsafe_path(info.orig_filename):
            raise _fail(AdminErrorCode.ZIP_UNSAFE_PATH)
        mode = info.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind == stat.S_IFLNK:
            raise _fail(AdminErrorCode.ZIP_SYMLINK)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise _fail(AdminErrorCode.ZIP_UNSAFE_PATH)
        if info.flag_bits & 0x1 or info.flag_bits & 0x40:
            raise _fail(AdminErrorCode.ZIP_ENCRYPTED)
        if info.compress_type not in _ALLOWED_METHODS:
            raise _fail(AdminErrorCode.ZIP_INVALID)
        folded = unicodedata.normalize("NFC", name).casefold()
        if folded in seen:
            raise _fail(AdminErrorCode.ZIP_DUPLICATE_NAME)
        seen.add(folded)
        if name.endswith("/"):
            continue
        if name.lower().endswith(_ARCHIVE_SUFFIXES):
            raise _fail(AdminErrorCode.ZIP_NESTED_ARCHIVE)
        if info.file_size > settings.upload_max_zip_ratio * max(info.compress_size, 1):
            raise _fail(AdminErrorCode.ZIP_RATIO_EXCEEDED)
        total += info.file_size
        if total > settings.upload_max_zip_uncompressed_bytes:
            raise _fail(AdminErrorCode.ZIP_UNCOMPRESSED_TOO_LARGE)
        members[name] = info
    if sum(1 for name in members if name != MANIFEST_FILENAME) > settings.upload_max_zip_files:
        raise _fail(AdminErrorCode.ZIP_TOO_MANY_FILES)
    return members


def _parse_manifest(raw: bytes, settings: Settings) -> list[Any]:
    def no_constants(value: str) -> Any:
        raise ValueError(value)

    try:
        doc = json.loads(raw.decode("utf-8"), parse_constant=no_constants)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise _fail(AdminErrorCode.MANIFEST_INVALID) from None
    if not isinstance(doc, dict) or set(doc) != {"version", "documents"}:
        raise _fail(AdminErrorCode.MANIFEST_INVALID)
    version = doc["version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise _fail(AdminErrorCode.MANIFEST_INVALID)
    if version != MANIFEST_VERSION:
        raise _fail(AdminErrorCode.MANIFEST_VERSION_UNSUPPORTED)
    documents = doc["documents"]
    if not isinstance(documents, list):
        raise _fail(AdminErrorCode.MANIFEST_INVALID)
    if len(documents) > settings.upload_max_zip_files:
        raise _fail(AdminErrorCode.ZIP_TOO_MANY_FILES)
    files = [d.get("file") for d in documents if isinstance(d, dict)]
    if len(set(f for f in files if isinstance(f, str))) != len(
        [f for f in files if isinstance(f, str)]
    ):
        raise _fail(AdminErrorCode.MANIFEST_INVALID)  # one file listed twice
    return documents


def _short(value: Any) -> str:
    return str(value)[:100]


def _plan_entry(
    index: int,
    raw: Any,
    members: dict[str, zipfile.ZipInfo],
    archive: zipfile.ZipFile,
    departments: dict[str, DepartmentOut],
    settings: Settings,
    pdf_check: PdfCheck,
) -> EntryPlan:
    if not isinstance(raw, dict):
        return EntryPlan(index, "", error_code=AdminErrorCode.MANIFEST_INVALID)
    file = raw.get("file")
    plan = EntryPlan(index, file if isinstance(file, str) else "")
    extra = set(raw) - _ENTRY_KEYS
    if extra or not isinstance(file, str) or not isinstance(raw.get("title"), str):
        plan.error_code = AdminErrorCode.MANIFEST_INVALID
        plan.detail = _short(sorted(extra)[0]) if extra else None
        return plan
    if _unsafe_path(file) or file.endswith("/"):
        plan.error_code = AdminErrorCode.ZIP_UNSAFE_PATH
        return plan
    info = members.get(file)
    if info is None or file == MANIFEST_FILENAME:
        plan.error_code = AdminErrorCode.MANIFEST_FILE_MISSING
        return plan
    try:
        plan.title = validate_title(raw["title"])
    except AppError:
        plan.error_code = AdminErrorCode.TITLE_INVALID
        return plan
    owner = raw.get("owner_department")
    if not isinstance(owner, str):
        plan.error_code = AdminErrorCode.MANIFEST_INVALID
        plan.detail = "owner_department"
        return plan
    if owner not in departments:
        plan.error_code = AdminErrorCode.UNKNOWN_DEPARTMENT
        plan.detail = _short(owner)
        return plan
    plan.owner = departments[owner]
    allowed = raw.get("allowed_departments")
    if allowed is None:
        plan.error_code = AdminErrorCode.ALLOWED_DEPARTMENTS_MISSING
        return plan
    if not isinstance(allowed, list) or not all(isinstance(s, str) for s in allowed):
        plan.error_code = AdminErrorCode.MANIFEST_INVALID
        plan.detail = "allowed_departments"
        return plan
    if not allowed:
        plan.error_code = AdminErrorCode.ALLOWED_DEPARTMENTS_EMPTY
        return plan
    unknown = next((s for s in allowed if s not in departments), None)
    if unknown is not None:
        plan.error_code = AdminErrorCode.UNKNOWN_DEPARTMENT
        plan.detail = _short(unknown)
        return plan
    plan.allowed = [departments[s] for s in dict.fromkeys(allowed)]
    if info.file_size > settings.upload_max_pdf_bytes:
        plan.error_code = AdminErrorCode.FILE_TOO_LARGE
        return plan
    try:
        validate_pdf(file.rsplit("/", 1)[-1], _read(archive, info), pdf_check)
    except AppError as exc:
        plan.error_code = AdminErrorCode(exc.code)
    return plan


def inspect_zip(
    data: bytes,
    settings: Settings,
    departments: dict[str, DepartmentOut],
    pdf_check: PdfCheck = check_pdf_structure,
) -> list[EntryPlan]:
    """Validate the archive and the manifest and return one plan per manifest entry.

    Raises ``AppError`` for an archive-level problem. Creates nothing."""
    if len(data) > settings.upload_max_zip_bytes:
        raise _fail(AdminErrorCode.ZIP_TOO_LARGE)
    _check_directory_size(data, settings)
    with _open(data) as archive:
        members = _validate_members(archive, settings)
        manifest = members.get(MANIFEST_FILENAME)
        if manifest is None:
            raise _fail(AdminErrorCode.MANIFEST_MISSING)
        if manifest.file_size > settings.upload_max_manifest_bytes:
            raise _fail(AdminErrorCode.MANIFEST_TOO_LARGE)
        documents = _parse_manifest(_read(archive, manifest), settings)
        listed = {
            d["file"] for d in documents if isinstance(d, dict) and isinstance(d.get("file"), str)
        }
        if any(n != MANIFEST_FILENAME and n not in listed for n in members):
            raise _fail(AdminErrorCode.ZIP_UNLISTED_FILE)
        return [
            _plan_entry(i, raw, members, archive, departments, settings, pdf_check)
            for i, raw in enumerate(documents)
        ]


def read_entry(data: bytes, file: str, settings: Settings) -> bytes:
    """The bytes of one member, bounded by the per-PDF limit. Used again at confirmation."""
    with _open(data) as archive:
        try:
            info = archive.getinfo(file)
        except KeyError:
            raise _fail(AdminErrorCode.MANIFEST_FILE_MISSING) from None
        if info.file_size > settings.upload_max_pdf_bytes:
            raise _fail(AdminErrorCode.FILE_TOO_LARGE)
        return _read(archive, info)
