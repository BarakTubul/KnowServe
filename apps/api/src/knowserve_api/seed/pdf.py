"""A tiny deterministic PDF generator for the seed documents (M2-05, Q5).

Output depends only on the arguments: no timestamps, no random ids, fixed object order, so the same
input yields the same bytes on every machine. It writes plain text pages in Helvetica (a standard
font, nothing embedded). It is not a general PDF library and not the Golden Dataset (DEF-01).

    python -m knowserve_api.seed.pdf        # rewrite the committed files under seed/data/
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from .specs import SEED_DOCUMENTS, SeedDocument

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
_WRAP = 78
_LINES_PER_PAGE = 44


def _escape(text: str) -> str:
    cleaned = text.encode("latin-1", "replace").decode("latin-1")
    return cleaned.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_stream(title: str, number: int, total: int, lines: list[str]) -> bytes:
    ops = ["BT", "/F2 16 Tf", "72 720 Td", f"({_escape(title)}) Tj", "ET"]
    ops += ["BT", "/F1 11 Tf", "14 TL", "72 690 Td"]
    for line in lines:
        ops.append(f"({_escape(line)}) Tj T*")
    ops += ["ET", "BT", "/F1 9 Tf", "72 40 Td", f"(Page {number} of {total}) Tj", "ET"]
    return "\n".join(ops).encode("latin-1")


def _paginate(paragraphs: list[str], pages: int) -> list[list[str]]:
    lines: list[str] = []
    for paragraph in paragraphs:
        lines.extend(textwrap.wrap(paragraph, _WRAP) or [""])
        lines.append("")
    result: list[list[str]] = [[] for _ in range(pages)]
    per_page = max(1, min(_LINES_PER_PAGE, -(-len(lines) // pages)))
    for index, line in enumerate(lines):
        result[min(index // per_page, pages - 1)].append(line)
    return result


def build_pdf(title: str, paragraphs: list[str], pages: int) -> bytes:
    """Return a ``pages``-page PDF with ``title`` as the heading of every page."""
    if pages < 1:
        raise ValueError("pages must be at least 1")
    page_lines = _paginate(paragraphs, pages)
    # Objects: 1 catalog, 2 page tree, 3 and 4 fonts, then (page, content) pairs.
    first_page = 5
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(pages))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    for i in range(pages):
        content_id = first_page + 2 * i + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        stream = _page_stream(title, i + 1, pages, page_lines[i])
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def render(document: SeedDocument) -> bytes:
    return build_pdf(document.title, list(document.paragraphs), document.pages)


def main() -> None:
    target = Path(__file__).parent / "data"
    target.mkdir(exist_ok=True)
    for document in SEED_DOCUMENTS:
        (target / document.filename).write_bytes(render(document))
        print(f"wrote {document.filename}")


if __name__ == "__main__":
    main()
