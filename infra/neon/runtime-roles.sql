-- Neon database roles for M1 (D2): a DDL role for migrations and a DML-only runtime role.
-- PREPARED ONLY. Nothing here has been run. The Owner runs it, section by section, in the Neon SQL
-- editor (or psql) against the production database, after reading each result.
--
-- DDL role = neondb_owner (Owner decision after the ownership check: it owns every public table). The runtime role is ks_runtime.
-- Do not paste passwords into this file or into SQL history: create the runtime role in the Neon
-- console (Roles -> New role, which generates a password), and copy the connection strings straight
-- into Secret Manager (see infra/terraform/README.md, "Owner steps for the migration job").
-- Neon behavior (role creation, pooled host names, default privileges) is from general knowledge
-- and is UNVERIFIED here; check each result.

-- ============================================================================================
-- 1. READ-ONLY: who owns what today (run first; decides neondb_owner)
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
-- REUSE that role as neondb_owner (the migration job keeps working with ownership unchanged) and only
-- create the runtime role. If the owner is something else, stop and ask: another role cannot
-- ALTER tables it does not own.

-- ============================================================================================
-- 2. The role ks_runtime exists (created in the Neon console, password stored by the Owner).
--    READ-ONLY inspection of what Neon gave it. Run as neondb_owner.
--    Roles created through the Neon console/API are, as far as I know, members of `neon_superuser`
--    (and so inherit broad rights such as pg_write_all_data and CREATEROLE). UNVERIFIED: check.
-- ============================================================================================
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolcanlogin
FROM pg_roles WHERE rolname = 'ks_runtime';

SELECT r.rolname AS member_of
FROM pg_auth_members m
JOIN pg_roles r ON r.oid = m.roleid
JOIN pg_roles u ON u.oid = m.member
WHERE u.rolname = 'ks_runtime';

SELECT has_schema_privilege('ks_runtime', 'public', 'CREATE')            AS schema_create,
       has_database_privilege('ks_runtime', current_database(), 'CREATE') AS database_create,
       has_database_privilege('ks_runtime', current_database(), 'CONNECT') AS database_connect;

SELECT table_name, privilege_type
FROM information_schema.role_table_grants WHERE grantee = 'ks_runtime' ORDER BY 1, 2;

SELECT pg_get_userbyid(defaclrole) AS for_role, defaclobjtype AS objtype, defaclacl
FROM pg_default_acl;

-- ============================================================================================
-- 2b. Corrections (run only what section 2 showed to be needed; each is idempotent)
--     If ks_runtime is a member of neon_superuser, pg_read_all_data, pg_write_all_data or any
--     other role, remove it, and clear the privileged attributes. Nothing else is touched.
-- ============================================================================================
REVOKE neon_superuser FROM ks_runtime;       -- only if listed above; skip if not a member
REVOKE pg_read_all_data FROM ks_runtime;     -- only if listed above
REVOKE pg_write_all_data FROM ks_runtime;    -- only if listed above
ALTER ROLE ks_runtime NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

-- ============================================================================================
-- 3. Grants for ks_runtime (DML only, no DDL, no ownership). Run as neondb_owner.
-- ============================================================================================
GRANT USAGE ON SCHEMA public TO ks_runtime;
-- No `REVOKE ... FROM PUBLIC` here: PostgreSQL 15+ (Neon runs 17/18) already withholds CREATE on
-- schema public from PUBLIC, and this script must not change other roles' rights. Section 2's
-- schema_create / database_create columns must both be false after the corrections.

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ks_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ks_runtime;

-- Objects created by FUTURE migrations (0002 creates users, sessions, ...) are owned by neondb_owner;
-- without default privileges the runtime role could not see them.
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ks_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO ks_runtime;

-- The runtime role does not need to touch Alembic's bookkeeping table.
REVOKE ALL ON TABLE alembic_version FROM ks_runtime;

-- Final read-only check (expect: schema_create false, database_create false, no extra memberships)
SELECT has_schema_privilege('ks_runtime', 'public', 'CREATE')            AS schema_create,
       has_database_privilege('ks_runtime', current_database(), 'CREATE') AS database_create;

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

-- After the first M1 migration has run (as neondb_owner through the migration job), re-run the
-- BEGIN/INSERT/ROLLBACK smoke on the new tables, for example:
--   BEGIN;
--   SELECT count(*) FROM departments;                -- expected 5
--   INSERT INTO usage_counters ... ; ROLLBACK;

-- ============================================================================================
-- 5. Connection strings (copy into Secret Manager from stdin; never into the repo or CI)
-- ============================================================================================
--   migration-database-url : neondb_owner role, DIRECT host (not the "-pooler" host)
--   database-url           : ks_runtime role, POOLED host ("-pooler")
-- Do not disable the previous `database-url` version until M1-AC11 (the migration job run)
-- has passed, so the runtime can be rolled back.
