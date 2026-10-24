# RAG chat, citations and evaluation

## AI system
- Framework: **LlamaIndex**, but keep control over authorization, lifecycle, job orchestration and citations in application code.
- LLM routed through **OpenRouter**, initially an OpenAI-family chat model; final model chosen by measured quality/cost. No user free-form model selection, automatic fallback or multicloud failover in MVP.
- Embeddings independently provided via OpenAI `text-embedding-3-small` initially (direct provider API). Record embedding model/version and embedding-index identity. Changing embedding model requires rebuilding/revalidating the corpus vector index; do not mix vector spaces.
- PyMuPDF4LLM per-page extraction, `SentenceSplitter` (initial 512/64 tokens) with preserved page metadata.
- `Authorized Retriever`: custom SQLAlchemy + pgvector SQL combines current revision, ready and current department permission in the DB **before** similarity order/Top-K. Top-K initially 5 with tunable similarity threshold calibrated on evaluation. No Reranker or keyword hybrid search in MVP.
- Multi-turn question rewriting may use prior messages but every turn performs new retrieval under current permissions. Never assume prior retrieved chunks remain authorized.
- Answer only supported organizational facts. Support partial answers if evidence partial; explicitly explain contradictions among documents, cite each relevant source; insufficient support => admit not found.

## Citations and streaming
- LlamaIndex may suggest source IDs; backend maps citations only to actual authorized retrieved chunk/document/revision/page references and rejects invented IDs.
- Distinguish deterministic citation existence/authorization validation from semantic grounding; grounding is evaluated separately. A source existing does not prove the claim is supported.
- Protected Viewer deep-link `/documents/:id?page=N` shows filename+page; check access when resolving/opening.
- Streaming via **SSE over POST Fetch stream** (`searching`, `generating`, token/delta, `done`, `error`), `AbortController` on Stop, backend cancel downstream token generation where possible, record aborted/partial response honestly. Final citation completion only after validation; consider permission revocation during stream.
- Store conversation and messages per identity/department, searchable title, rename, delete, history; protect historical text when source access revoked.

## Evaluation suite
- Hybrid Golden Dataset: human-written + LLM-synthetic samples; **every sample human verified**, with expected sources/pages/department/revision and negatives/partial/conflicting/multi-turn/prompt-injection cases.
- Retrieval metrics doc and chunk level: Recall@K, Precision@K, MRR; retain stable references across re-chunking.
- Answer/citation quality: deterministic checks + LLM judge + human calibration. Report security failures as hard failures, never hide them in an aggregate score.
- Progressive gates: deterministic/security checks on every PR, small real-model checks only for relevant changes, full real-model suite manually/periodically. Initial AI thresholds informational until enough baseline; later gate regressions.
- Immutable approved baseline changed only after human review, version dataset/model/config/doc revisions. Rerun only suspicious/borderline cases and distinguish judge stochasticity from model variability.
- Outputs `evaluation_report.md` and `evaluation_results.json`: per-case details, evidence, deltas, failures, coverage/gaps and provenance.

## Deferred distinct task
- **How to curate a realistic, interesting, varied fictional organization document corpus** is a separately deferred topic. Do not decide it during this documentation reconciliation.
