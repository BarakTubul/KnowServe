# ADR 0002: Database for tests and CI

Status: accepted by the Owner (M0-01). Date: 2026-10-24.

## Decision
- Integration tests run against a real PostgreSQL with the `vector` extension (TEST-06), never SQLite or mocks for SQL.
- Local: the compose `db` service (`pgvector/pgvector:pg16`, host port 5433) with a disposable `knowserve_test` database.
- CI: a GitHub Actions service container from the same image. Both use `KS_TEST_DATABASE_URL`.
- The test session drops and recreates the `public` schema in the test database, then runs `alembic upgrade head`, so migrations are exercised on every run (M0-AC03). Each test truncates the tables it used.
- A missing database makes integration tests **fail**, not skip.

## Consequences
- Tests must never be pointed at a non-disposable database. The only configured default is the local compose test database.
- The same migration is run against Neon only in the authorized deployment (M0-06), never from this local work.
