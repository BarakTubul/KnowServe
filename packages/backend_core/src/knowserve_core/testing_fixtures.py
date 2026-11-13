"""Fixture builders for M3 tests: small PDFs and hostile ZIPs (M3-01).

Everything is built in memory and is deterministic (no timestamps, no random ids), so a test that
fails once fails the same way again. Not used by production code. The PDF builders write only the
shapes the ingestion tests need; they are not a general PDF writer. The Worker slice checks them
against the real extractor in M3-02a, so a wrong fixture shows up there. They were also opened
with PyMuPDF once during M3-01 (page counts, text, the NUL character, the password, the corrupt
file). The signed QStash delivery helper is `sign_qstash_delivery` in the root `conftest.py`.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any

# --- PDFs -----------------------------------------------------------------------------------

_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _escape(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch in "()\\":
            out.append("\\" + ch)
        elif ch == "\x00":
            out.append("\\000")
        elif ord(ch) < 32 or ord(ch) > 126:
            out.append("?")
        else:
            out.append(ch)
    return "".join(out)


def _page_stream(text: str | None) -> bytes:
    """A content stream: one line of text, or (``None``) only an inline image and no text."""
    if text is None:
        # 2x2 grey inline image, no text operators: an "image-only" (scanned) page.
        return b"q 200 0 0 200 100 500 cm BI /W 2 /H 2 /CS /G /BPC 8 ID \x00\x80\x80\xff EI Q"
    return f"BT /F1 12 Tf 72 720 Td ({_escape(text)}) Tj ET".encode("latin-1")


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def make_pdf(pages: Sequence[str | None], *, password: str | None = None) -> bytes:
    """A valid PDF with one page per item: the item is the page text, or ``None`` for an
    image-only page. With ``password`` the file is encrypted (RC4, 40 bit) and needs it to open."""
    if not pages:
        raise ValueError("a PDF needs at least one page")
    n = len(pages)
    # Object numbers: 1 catalog, 2 pages, 3 font, then (page, content) pairs from 4.
    objects: dict[int, bytes] = {}
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    file_id = hashlib.md5(b"knowserve-fixture" + str(n).encode()).digest()
    enc_key = b""
    enc_dict = b""
    if password is not None:
        owner = hashlib.md5(b"owner-" + password.encode()).hexdigest().encode()
        user_pad = (password.encode() + _PAD)[:32]
        owner_pad = (owner + _PAD)[:32]
        o_key = hashlib.md5(owner_pad).digest()[:5]
        o_value = _rc4(o_key, user_pad)
        perms = -4
        enc_key = hashlib.md5(
            user_pad + o_value + perms.to_bytes(4, "little", signed=True) + file_id
        ).digest()[:5]
        u_value = _rc4(enc_key, _PAD)
        enc_dict = (
            b"<< /Filter /Standard /V 1 /R 2 /P -4 /O <"
            + o_value.hex().encode()
            + b"> /U <"
            + u_value.hex().encode()
            + b"> >>"
        )

    def stream_obj(num: int, data: bytes) -> bytes:
        if password is not None:
            obj_key = hashlib.md5(enc_key + num.to_bytes(3, "little") + b"\x00\x00").digest()[:10]
            data = _rc4(obj_key, data)
        return b"<< /Length " + str(len(data)).encode() + b" >>\nstream\n" + data + b"\nendstream"

    for i, text in enumerate(pages):
        page_num, content_num = 4 + 2 * i, 5 + 2 * i
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
        ).encode()
        objects[content_num] = stream_obj(content_num, _page_stream(text))
    encrypt_num = 4 + 2 * n
    if password is not None:
        objects[encrypt_num] = enc_dict

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = out.tell()
        out.write(f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n")
    size = max(objects) + 1
    xref = out.tell()
    out.write(f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n")
    for num in range(1, size):
        out.write(f"{offsets[num]:010d} 00000 n \n".encode())
    trailer = f"trailer\n<< /Size {size} /Root 1 0 R /ID [<{file_id.hex()}> <{file_id.hex()}>]"
    if password is not None:
        trailer += f" /Encrypt {encrypt_num} 0 R"
    out.write(trailer.encode() + f" >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def pdf_two_pages() -> bytes:
    return make_pdf(["Leave policy. Employees receive twenty days.", "Expenses are reimbursed."])


def pdf_image_only() -> bytes:
    """No extractable text (OPEN-17, `NO_EXTRACTABLE_TEXT`)."""
    return make_pdf([None, None])


def pdf_with_nul_in_text() -> bytes:
    """Text containing a NUL character, which PostgreSQL text cannot store (finding F18)."""
    return make_pdf(["before\x00after"])


def pdf_many_pages(count: int) -> bytes:
    return make_pdf([f"Page {i} text." for i in range(1, count + 1)])


def pdf_encrypted() -> bytes:
    return make_pdf(["Secret text."], password="fixture-password")


def pdf_corrupt() -> bytes:
    """A correct signature and a body that is not a PDF."""
    return b"%PDF-1.4\n" + b"this is not a valid pdf body " * 8


def not_a_pdf() -> bytes:
    return b"PK\x03\x04 plain text renamed to .pdf"


# --- ZIP and manifest ---------------------------------------------------------------------------


def manifest_json(documents: Sequence[Mapping[str, Any]], version: int = 1) -> bytes:
    return json.dumps({"version": version, "documents": list(documents)}).encode()


def manifest_entry(
    file: str,
    title: str = "Fixture document",
    owner_department: str = "finance",
    allowed_departments: Sequence[str] | None = ("finance",),
) -> dict[str, Any]:
    """One manifest entry. Department values are slugs (OPEN-31 D10). Pass
    ``allowed_departments=None`` to leave the field out."""
    entry: dict[str, Any] = {"file": file, "title": title, "owner_department": owner_department}
    if allowed_departments is not None:
        entry["allowed_departments"] = list(allowed_departments)
    return entry


def make_zip(
    files: Mapping[str, bytes],
    manifest: bytes | Mapping[str, Any] | None = None,
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    """A ZIP with ``files`` and, unless ``manifest`` is ``None``, a ``manifest.json``.

    ``manifest`` may be raw bytes (for malformed JSON cases) or a mapping that is dumped as JSON.
    Names are written exactly as given, including hostile ones.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as archive:
        for name, data in files.items():
            archive.writestr(_info(name), data, compress_type=compression)
        if manifest is not None:
            raw = manifest if isinstance(manifest, bytes) else json.dumps(dict(manifest)).encode()
            archive.writestr(_info("manifest.json"), raw, compress_type=compression)
    return buf.getvalue()


def _info(name: str, *, mode: int = 0o100644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.external_attr = mode << 16
    return info


def zip_with_symlink() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr(_info("link.pdf", mode=0o120777), b"/etc/passwd")
        archive.writestr("manifest.json", manifest_json([manifest_entry("link.pdf")]))
    return buf.getvalue()


def zip_bomb(ratio_bytes: int = 5 * 1024 * 1024) -> bytes:
    """One entry of zeros that deflates to a tiny size (a very high ratio)."""
    return make_zip({"big.pdf": b"\x00" * ratio_bytes}, manifest_json([manifest_entry("big.pdf")]))


def zip_with_encrypted_flag() -> bytes:
    """An entry whose general-purpose flag marks it encrypted (the data is not really encrypted)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        info = _info("secret.pdf")
        archive.writestr(info, pdf_two_pages())
        archive.writestr("manifest.json", manifest_json([manifest_entry("secret.pdf")]))
    raw = bytearray(buf.getvalue())
    # Set bit 0 of the general-purpose flag in every local and central header.
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = 0
        while (at := raw.find(signature, start)) != -1:
            raw[at + offset] |= 0x01
            start = at + 4
    return bytes(raw)


HOSTILE_NAMES = (
    "../evil.pdf",
    "..\\evil.pdf",
    "/etc/evil.pdf",
    "C:\\evil.pdf",
    "folder/../../evil.pdf",
    "nul\x00.pdf",
    "bidi\u202egnp.pdf",
)
