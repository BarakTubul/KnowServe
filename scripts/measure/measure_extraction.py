"""M3-00b: local measurement of PDF extraction and chunking (not run in CI).

Builds three synthetic text PDFs (small, medium, and the largest allowed page count), runs the real
extraction child code and the real chunker in fresh interpreters, and records wall time and peak
memory per page. Writes JSON to the path given by --json. The numbers are for sizing the Worker
(OPEN-31 D2); they describe this machine, and docs/milestones/M3/measurements.md says which one.

    uv run python scripts/measure/measure_extraction.py --json out.json [--repeats 3]

Synthetic pages are dense Helvetica text (about 45 lines each) with no images or vector graphics.
Real documents with tables, drawings or embedded fonts cost more; the report says so.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORDS = (
    "leave policy employee manager request approval budget quarter report expense travel contract "
    "review clause incident runbook escalation severity customer security access department "
    "document revision handbook procedure compliance audit finance legal operations engineering"
).split()


def dense_text(page: int, lines: int = 45, words_per_line: int = 11) -> str:
    out = []
    for line in range(lines):
        ws = [WORDS[(page * 7 + line * 3 + i * 5) % len(WORDS)] for i in range(words_per_line)]
        out.append(" ".join(ws).capitalize() + ".")
    return "\n".join(out)


def build_pdf(pages: int) -> bytes:
    from knowserve_core import testing_fixtures as tf

    def stream(text: str | None) -> bytes:
        assert text is not None
        body = ["BT /F1 10 Tf 12 TL 40 760 Td"]
        for line in text.split("\n"):
            body.append(f"({tf._escape(line)}) Tj T*")
        body.append("ET")
        return "\n".join(body).encode("latin-1")

    original = tf._page_stream
    tf._page_stream = stream  # type: ignore[assignment]
    try:
        return tf.make_pdf([dense_text(i) for i in range(1, pages + 1)])
    finally:
        tf._page_stream = original  # type: ignore[assignment]


def peak_memory_mb() -> float:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return counters.PeakWorkingSetSize / 2**20
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 2**20 if sys.platform == "darwin" else peak / 1024


def inner(mode: str, path: str) -> None:
    """Runs in a fresh interpreter so the peak memory belongs to this one job."""
    started = time.perf_counter()
    result: dict = {}
    if mode == "baseline":
        import pymupdf  # noqa: F401
        import pymupdf4llm  # noqa: F401
    elif mode == "extract":
        from knowserve_core import _pdf_extract_child as child

        data = Path(path).read_bytes()
        t0 = time.perf_counter()
        out = child.extract(data, 10_000)
        result = {"extract_seconds": time.perf_counter() - t0, "ok": out["ok"]}
        if out["ok"]:
            Path(path + ".pages.json").write_text(json.dumps(out["pages"]), encoding="utf-8")
    elif mode == "chunk":
        from knowserve_core.chunking import chunk_pages
        from knowserve_core.pdf_extraction import ExtractedPage

        texts = json.loads(Path(path).read_text(encoding="utf-8"))
        pages = [ExtractedPage(i + 1, t) for i, t in enumerate(texts)]
        t0 = time.perf_counter()
        chunks = chunk_pages(pages, chunk_size_tokens=512, chunk_overlap_tokens=64)
        result = {"chunk_seconds": time.perf_counter() - t0, "chunks": len(chunks)}
    else:
        raise SystemExit(f"unknown mode {mode}")
    result["total_seconds"] = time.perf_counter() - started
    result["peak_mb"] = peak_memory_mb()
    print("RESULT " + json.dumps(result))


def run_inner(mode: str, path: str = "") -> dict:
    proc = subprocess.run(
        [sys.executable, __file__, "--inner", mode, path],
        capture_output=True,
        text=True,
        timeout=900,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[7:])
    raise RuntimeError(f"{mode} failed: {proc.stderr[-800:]}")


def median(values: list[float]) -> float:
    return sorted(values)[len(values) // 2]


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--inner":
        inner(sys.argv[2], sys.argv[3])
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--sizes", default="5,50,300")
    args = ap.parse_args()

    report: dict = {
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "baseline": [run_inner("baseline") for _ in range(args.repeats)],
        "sizes": [],
    }
    with tempfile.TemporaryDirectory() as tmp:
        for pages in (int(x) for x in args.sizes.split(",")):
            pdf = Path(tmp) / f"dense-{pages}.pdf"
            pdf.write_bytes(build_pdf(pages))
            ext = [run_inner("extract", str(pdf)) for _ in range(args.repeats)]
            chk = [run_inner("chunk", str(pdf) + ".pages.json") for _ in range(args.repeats)]
            report["sizes"].append(
                {
                    "pages": pages,
                    "pdf_bytes": pdf.stat().st_size,
                    "extract_seconds": median([r["extract_seconds"] for r in ext]),
                    "extract_total_seconds": median([r["total_seconds"] for r in ext]),
                    "extract_peak_mb": max(r["peak_mb"] for r in ext),
                    "chunk_seconds": median([r["chunk_seconds"] for r in chk]),
                    "chunk_total_seconds": median([r["total_seconds"] for r in chk]),
                    "chunk_peak_mb": max(r["peak_mb"] for r in chk),
                    "chunks": chk[0]["chunks"],
                }
            )
    Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
