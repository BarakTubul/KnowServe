# M3-00b: extraction and chunking measurements

Local baseline for Worker sizing (OPEN-31 D2). It is input to M3-09. Nothing here ran in the cloud and nothing was deployed.

## How it was measured
- Script: `scripts/measure/measure_extraction.py` (not run in CI). Run it with `uv run python scripts/measure/measure_extraction.py --json out.json`.
- Each job runs in a fresh Python process, so the peak memory belongs to that job. Wall time is the median of 3 runs, peak memory the maximum of 3.
- Extraction measures the real child code (`_pdf_extract_child.extract`, PyMuPDF4LLM 0.3.4 on PyMuPDF 1.28.2). Chunking measures `chunk_pages` (LlamaIndex `SentenceSplitter`, bundled cl100k vocabulary, 512/64), including the LlamaIndex import.
- Machine: Windows 11, Python 3.11.15, 16 logical CPUs, run on 2026-11-13. Peak memory is the Windows peak working set. Cloud Run has a slower, smaller CPU and uses Linux, so treat the times as a lower bound.
- Input: synthetic PDFs of dense Helvetica text (about 45 lines, 3.4 KB of text per page), with no images, no vector graphics and no tables. These are not real documents.

## Results

| Pages | PDF size | Extraction time | Extraction time per page | Extraction peak memory | Chunking time (after a 1.3 s import) | Chunking process peak memory | Chunks |
|---|---|---|---|---|---|---|---|
| 5 | 24 KB | 0.65 s | 0.13 s | 60 MiB | 1.36 s | 139 MiB | 10 |
| 50 | 238 KB | 5.4 s | 0.11 s | 61 MiB | 1.32 s | 139 MiB | 100 |
| 300 (the D1 maximum) | 1.4 MB | 33.7 s | 0.11 s | 68 MiB | 1.59 s | 141 MiB | 600 |

- An interpreter with PyMuPDF and PyMuPDF4LLM imported and nothing else peaks at 48 MiB.
- Extraction time grows linearly with the page count. Memory grows by about 0.03 MiB per page.
- Chunking takes about 1.3 s to import LlamaIndex and then about 1 ms per page. LlamaIndex and the tokenizer account for roughly 90 MiB of the chunking process.
- Most of the extraction time is PyMuPDF4LLM's graphics analysis. On the 300-page file, plain `page.get_text()` took 0.27 s, PyMuPDF4LLM with graphics 32.0 s and PyMuPDF4LLM with `ignore_graphics=True` 8.8 s (one run each). The last option is not used. It also affects table detection, and the effect on real tables was not measured.

## Sizing conclusions (input to M3-09)

These follow from the numbers above. They are not a request to raise anything.

1. **Memory: no increase is justified by extraction.** The child peaks at 68 MiB for the largest allowed page count, and the chunking and LlamaIndex part peaks at about 141 MiB. The Worker process also holds the PDF bytes (up to 20 MiB, plus a copy in the pipe), the embedding batches, the vectors of one document and the FastAPI and SQLAlchemy baseline, which were not measured separately. A rough sum for one job is 250 to 350 MiB, which fits in the current 512 MiB. Keep 512 MiB and check it on Cloud Run in M3-AC23 with a real large document.
2. **Concurrency: this is the setting the numbers do change.** `infra/terraform/gcp_cloud_run.tf` sets no concurrency for the Worker, so Cloud Run uses its default of 80 requests per instance. D1 allows 10 documents in flight. Ten jobs landing on one instance at about 200 MiB each would exceed 512 MiB. Set the Worker concurrency to 1. A value of 2 would still be tight at 512 MiB. This lowers a limit and costs nothing; it only means more instances start under load. Scale-to-zero (COST-01) stays.
3. **Extraction timeout: the default of 60 s is too tight for the largest document.** `KS_PDF_EXTRACTION_TIMEOUT_SECONDS` defaults to 60. A 300-page text PDF took 34 s on this fast machine, so a CPU two times slower would hit the limit and the job would fail with `PROCESSING_TIMEOUT` on every attempt. Raise the setting to 120 s (a configuration value, no infrastructure change) or switch the extraction option as described above. This needs the Owner's decision on `settings.py`, which this slice does not edit.
4. **Request timeout: no change from these numbers.** The default 300 s covers extraction (up to about 34 s here, perhaps 70 to 135 s on Cloud Run), chunking (under 2 s) and the database writes. Embedding time for 600 chunks (about 10 batches of 64) was not measured because it needs the provider. Only the extraction and chunking part is covered here. Revisit if the Cloud Run run in M3-AC23 shows a document above 200 s.
5. **CPU: one vCPU is enough.** Extraction is single-threaded.

## Limits of this measurement
- Synthetic text only. Pages with tables, drawings, embedded fonts or large images were not measured and will be slower and larger. A 20 MiB image-heavy PDF was not measured.
- The embedding stage, the database writes and the Worker application baseline are not included.
- One machine. Cloud Run numbers (M3-AC23) replace these for any decision to apply infrastructure changes.
- Hebrew and other right-to-left text was not measured (plan section 8).
