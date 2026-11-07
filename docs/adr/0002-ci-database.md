# ADR 0002: Database for tests and CI

Status: accepted by the Owner (M0-01). Date: 2026-10-24.

## Decision
- Integration tests run against a real PostgreSQL with the `vector` extension (TEST-06), never SQLite or mocks for SQL.
- Local: the compose `db` service (`pgvector/pgvector:0.8.6-pg18` since M2-PG; it was `pg16` before, see below; host port 5433) with a disposable `knowserve_test` database.
- CI: a GitHub Actions service container from the same image. Both use `KS_TEST_DATABASE_URL`.
- The test session drops and recreates the `public` schema in the test database, then runs `alembic upgrade head`, so migrations are exercised on every run (M0-AC03). Each test truncates the tables it used.
- A missing database makes integration tests **fail**, not skip.

## Consequences
- Tests must never be pointed at a non-disposable database. The only configured default is the local compose test database.
- The same migration is run against Neon only in the authorized deployment (M0-06), never from this local work.

## Update 2026-11-07: PostgreSQL 18 (M2-PG, OPEN-28 Q11, roadmap D5)
- Compose and the CI service container now use `pgvector/pgvector:0.8.6-pg18`. Production Neon runs PostgreSQL 18.6 with pgvector 0.8.6 (M0 test plan AC03), so the major version and the pgvector minor version match. The tag was confirmed to exist on Docker Hub on 2026-11-07 (published for linux/amd64 and linux/arm64; the floating `pg18` tag already points at pgvector 0.8.7, which is why the exact version is pinned).
- The PostgreSQL 18 image stores data in a versioned subdirectory of `/var/lib/postgresql`, so the Compose volume is now `db-data-pg18` mounted there. The old `db-data` volume (PostgreSQL 16 data) is not touched or deleted; nobody has to migrate it, because the test database is disposable and is recreated by the test session (see above). Remove the old volume by hand when you no longer need it.
- Migrations `0001` and `0002` and the affected tests must pass on this image. Migration `0003` is tested on PostgreSQL 18 once it exists (M2-01).
- Known differences that remain: Neon is a managed service with its own extension build and pooler, so Neon-only behavior stays release evidence (TEST-11). Developers who run a native PostgreSQL on port 5433 instead of Compose (the owner's machine does, on version 16) are not covered by this change; start the Compose `db` service or upgrade the native server to compare with production.
- Production Neon is not changed by this update.
- Verification status on 2026-11-07: the image tag exists; `docker compose config` and the `ci.yml` YAML parse. The migrations and the test suite have **not** yet run on PostgreSQL 18: the Docker engine on the development machine was stopped (the `docker-desktop` WSL distribution is stopped and `docker ps` does not answer), and the native PostgreSQL 18 service on port 5432 has no pgvector extension and is the owner's own server, so it was not used. The first `ci` run on the branch, or a local run once Docker is started, provides the evidence (M2-AC17 stays open until then).
