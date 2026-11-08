# Cloud Run rollback note (M2-RB)

Requirements: INFRA-05, TEST-16, M2-AC20. Written before the first production migration of M2. The procedure has not been exercised; nothing here has been run against production.

## Principles
- Rollback is a human decision, not automation (TEST-16).
- Application rollback and database rollback are separate decisions. Rolling the application back never needs a schema change.
- Migrations are expand-only where possible, so the previous revision keeps working on the new schema (INFRA-05).

## What `0003` changes
Migration `0003_m2_documents` only adds three tables: `documents`, `document_revisions`, `document_department_access`. It alters no existing table, column or constraint and moves no data. The M1 API and Worker revisions never read or write those tables, so they run unchanged against a database at `0003`. Rolling the application back therefore does not touch the schema.

## Order of events in a deploy
`deploy.yml` runs the migration job first, then rolls the API and the Worker. A failed migration stops the run before any service changes. So after a deploy there are two states to reason about: the migration ran and the rollout failed, or both succeeded and a problem shows up later.

## Application rollback (revision rollback)
1. Find the last healthy revision of each service (`knowserve-api`, `knowserve-worker`) in the Cloud Run console or with `gcloud run revisions list`.
2. Check it is compatible with the current schema (next section).
3. Route traffic back to that revision: `gcloud run services update-traffic <service> --to-revisions=<revision>=100` for each service that needs it. Both services are rolled back together if the failing change touched both.
4. Check `/health/ready` on each service and read a log window for errors.
5. Leave the database as it is.

The commands are listed so the step is clear. They need a person with deploy rights and are not run by an agent without approval.

## Check that the previous revision works with `0003`
Before routing traffic back:
1. Confirm the target revision is built from a commit before the M2 change set, so it contains no code that reads the three new tables.
2. Confirm the current database revision with `alembic current` through the migration job, or read `alembic_version`. Expected `0003`.
3. Confirm `0003` is the only migration newer than the revision's own head. If a later migration alters or drops an existing column, stop: that is a rollback-incompatible migration and needs its own decision.
4. Call `/health/ready` on the old revision before sending it traffic (use a tagged revision URL), and run one authenticated read through the proxy.

## Database rollback (separate decision)
Dropping `0003` (`alembic downgrade 0002`) deletes the three tables and everything in them, including seeded documents and, after M3, uploaded documents. It is not part of an application rollback. Decide it only if the tables themselves are the problem, take a Neon branch or backup first, and run it through the migration job under the `production` approval. The downgrade is tested on a disposable database (`test_m2_downgrade_0003_removes_document_tables_and_upgrades_again`).

## Not covered
- A migration that is not backward compatible. Each such migration says so in its PR (INFRA-05) and gets its own note.
- Object storage. Rolling the application back leaves R2 objects in place; they are unreferenced by the old revision.
- Cloudflare Pages. Rolling back the frontend is a separate Pages deployment rollback.
