-- Neon database roles for M1 (D2): a DDL role for migrations and a DML-only runtime role.
-- PREPARED ONLY. Nothing here has been run. The Owner runs it, section by section, in the Neon SQL
-- editor (or psql) against the production database, after reading each result.
--
-- Names are examples. <DDL> is the role that owns the tables today (section 1 tells you which).
-- Do not paste passwords into this file or into SQL history: create the runtime role in the Neon
-- console (Roles -> New role, which generates a password), and copy the connection strings straight
-- into Secret Manager (see infra/terraform/README.md, "Owner steps for the migration job").
-- Neon behavior (role creation, pooled host names, default privileges) is from general knowledge
-- and is UNVERIFIED here; check each result.

-- ============================================================================================
-- 1. READ-ONLY: who owns what today (run first; decides <DDL>)
-- ============================================================================================
SELECT current_user, version();

SELECT tablename, tableowner
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

SELECT n.nspname AS schema, pg_get_userbyid(n.nspowner) AS schema_owner
FROM pg_namespace n WHERE n.nspname = 'public';

SELECT c.relname AS sequence, pg_get_userbyid(c.relowner) AS owner
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'S';

SELECT rolname, rolsuper, rolcreaterole, rolcanlogin FROM pg_roles
WHERE rolname NOT LIKE 'pg\_%' ORDER BY rolname;

SELECT version_num FROM alembic_version;   -- expected: 0001 before the first M1 migration

-- Decision: if every table above has the same owner (the role in today's `database-url`),
-- REUSE that role as <DDL> (the migration job keeps working with ownership unchanged) and only
-- create the runtime role. If the owner is something else, stop and ask: another role cannot
-- ALTER tables it does not own.

-- ============================================================================================
-- 2. Create the runtime role in the Neon console (generated password), named ks_runtime.
--    Then run the rest as <DDL> (the owner) or a Neon admin role.
-- ============================================================================================

-- ============================================================================================
-- 3. Grants for ks_runtime (DML only, no DDL, no ownership)
-- ============================================================================================
GRANT USAGE ON SCHEMA public TO ks_runtime;
REVOKE CREATE ON SCHEMA public FROM ks_runtime;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;          -- no role may create objects in public

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ks_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ks_runtime;

-- Objects created by FUTURE migrations (0002 creates users, sessions, ...) are owned by <DDL>;
-- without default privileges the runtime role could not see them.
ALTER DEFAULT PRIVILEGES FOR ROLE <DDL> IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ks_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE <DDL> IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO ks_runtime;

-- The runtime role does not need to touch Alembic's bookkeeping table.
REVOKE ALL ON TABLE alembic_version FROM ks_runtime;

-- ============================================================================================
-- 4. Verify as ks_runtime (connect with the NEW runtime URL; use a transaction you roll back)
-- ============================================================================================
-- Expected to work:
BEGIN;
SELECT count(*) FROM jobs;
INSERT INTO jobs (job_type, correlation_id) VALUES ('grant_smoke', 'req_grant_smoke');
ROLLBACK;

-- Expected to FAIL with "permission denied" / "must be owner":
--   CREATE TABLE ks_should_fail (id int);
--   ALTER TABLE jobs ADD COLUMN ks_should_fail int;
--   DROP TABLE outbox;
--   SELECT * FROM alembic_version;
--   TRUNCATE users;     -- only after migration 0002 exists; TRUNCATE is not granted

-- After the first M1 migration has run (as <DDL> through the migration job), re-run the
-- BEGIN/INSERT/ROLLBACK smoke on the new tables, for example:
--   BEGIN;
--   SELECT count(*) FROM departments;                -- expected 5
--   INSERT INTO usage_counters ... ; ROLLBACK;

-- ============================================================================================
-- 5. Connection strings (copy into Secret Manager from stdin; never into the repo or CI)
-- ============================================================================================
--   migration-database-url : <DDL> role, DIRECT host (not the "-pooler" host)
--   database-url           : ks_runtime role, POOLED host ("-pooler")
-- Do not disable the previous `database-url` version until M1-AC11 (the migration job run)
-- has passed, so the runtime can be rolled back.
