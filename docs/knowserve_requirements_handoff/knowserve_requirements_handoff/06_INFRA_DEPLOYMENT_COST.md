# Cloud architecture, deployment and operations

## Environments and workflow
- Development: Docker Compose for API, worker and local pgvector DB where practical; React via Vite local. CI uses ephemeral tests and resources; one Production environment. **No permanent Staging**.
- Cloudflare Pages hosts static frontend. Google Cloud Run hosts separate FastAPI and Worker HTTP services. Neon PostgreSQL+pgvector; R2 private objects; QStash signed deliveries; Cloud Scheduler recovers outbox; Resend email.
- Confirm provider interoperability, quotas, free-tier conditions, region/cold starts, Cloud Run streaming and request timeouts, QStash worker invocation and signatures, and real hosting cost in **early M0 deployment spike**. The target is a working public demo at **$0–$5/month** incl limited AI usage; this is an aspiration, not a guarantee.
- Auto Production deploy on merge to `main` **only after human approved milestone PR** and CI passed. GitHub Actions tests, container builds, deploy and smoke tests. Cloud Run revision rollback where safe; DB migrations must be backward-compatible and handled explicitly if rollback incompatible.
- Terraform manages supported infrastructure resources, IAM, deployment settings; protected remote State and locking. Document unsupported IaC gaps; avoid secrets in State. Image release can be independent of Terraform apply.
- Secrets in Google Secret Manager (per-service IAM). Local `.env` private, `.env.example` placeholder. GitHub Actions via OIDC/WIF.
- Basic provider backups only; do not promise independent/complete backup solution on free tiers. R2 object durability is not equivalent to a versioned recovery backup.

## Operational reliability
- Structured JSON logs to stdout/stderr and Google Cloud Logging, request/correlation IDs across request/job phases; basic Cloud Monitoring metrics and alerts. Avoid full distributed tracing/Sentry initially.
- Cost controls at application level: anonymous and registered quotas, atomic global token/dollar reservation, per-request caps, parallel request caps, provider bill alerts and an AI kill switch.
- On exhausted AI budget, disable live LLM generation but preserve authorized document reading and chat history; optional sample AI exchanges are preverified and labeled.
- Database/Auth outage fails closed. LLM outage degrades chat but never prevents permitted docs from being read.
- Worker endpoint exposed on HTTPS only for valid signed QStash deliveries and eligible DB job; do not treat URL secrecy as authentication.
