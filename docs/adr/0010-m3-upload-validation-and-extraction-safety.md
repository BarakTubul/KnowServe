# ADR 0010: M3 upload validation, limits and extraction safety

Status: accepted by the Owner on 2026-11-13 (OPEN-31 D1, D2, D6, D7, D11), contract implemented in M3-01.

## Decisions
- **Limits** are configuration with the D1 defaults: PDF 20 MiB and 300 pages; ZIP 25 MiB, 20 PDFs,
  100 MiB uncompressed, 20:1 ratio per entry, manifest 256 KiB; 10 documents in flight; 50 new
  documents per UTC day. Settings validate that they are consistent.
- **Server-generated storage keys** (`documents/{document_id}/{revision_id}.pdf`). Client file names
  never reach a key. Archives are read in memory and never extracted to disk.
- **Extraction in a child process** with a hard timeout (`KS_PDF_EXTRACTION_TIMEOUT_SECONDS`), so a
  parser hang or native crash fails one attempt and not the Worker (D11).
- **Separate R2 credentials.** The API reads, writes and deletes; the Worker is read only (D6).
  `ObjectStore.delete` is idempotent and used by the API to clean up after a failed transaction.
- **Soft delete only** in M3. An in-flight job checks `deleted_at` in its publish transaction and ends
  with `DOCUMENT_DELETED` (D7).
- **Worker sizing** changes only from M3-00b measurements (D2).
- **Embeddings** come from an `EmbeddingProvider`. The deterministic fake is refused when
  `KS_ENV=production`.

## Consequences
M3-02a and M3-03 implement these rules; their tests carry the security hard gates of the plan.
