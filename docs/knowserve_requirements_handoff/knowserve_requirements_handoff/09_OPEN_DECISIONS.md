# Open decisions, assumptions and deliberate deferrals

## Not yet decided (do not fabricate)
- M0 Shared Core change ownership: user selected **focused Shared Domain Core**, but has **NOT yet selected** between Owner-owned vs dedicated Core Agent vs distributed authorship. Proposed Owner-owned remains a recommendation, not binding.
- Final OpenAI-family chat model via OpenRouter (quality/cost Benchmark required).
- Retrieval threshold and final `top_k`, chunk size/overlap are tuning parameters; initial 5, 512, 64 are baselines not benchmarks.
- Exact CSRF implementation, precise cookie site/domain topology, quotas/concurrency/token and file size/count limits.
- Exact Terraform backend, cloud resource/provider feasibility, actual costs/quotas, GCP deployment regions, secret manager limits.
- M0 detailed concurrency/integration sequencing and developer onboarding scripts.
- Detailed thresholds/evaluation corpus sample count and AI judge selection; these are not reasons to re-open the chosen evaluation strategy.
- Whether provider-native postgres backup/restore offers acceptable recovery in actual selected free tiers.

## Deferred by explicit user instruction
- Design of a varied, realistic and interesting fictional KnowServe document corpus: **defer, do not expand in the current reconciliation**.
- Google OAuth, OCR, custom model chooser, full tracing and Sentry, sophisticated hybrid retrieval/reranker, standalone AV, large admin system are not required MVP features.

## Review-required tensions
- Very low public-demo cloud spend ($0–$5/month including modest AI usage) may not be possible with desired independent managed services and traffic. Verify, don't guarantee.
- Fast path publish after DB commit + scheduled reconciliation is at-least-once. Prove idempotent handling rather than claiming exactly-once delivery.
- 'Docs restricted immediately after permission revocation' vs already-streamed text and persisted historical chat: specify server-side stop/redaction expectations carefully; no technical mechanism can unsend content already delivered to the client.
- Docs-only reconciliation must preserve `Known gaps` reflecting that existing backend/FRONTEND source remains legacy until the later implementation milestones.
