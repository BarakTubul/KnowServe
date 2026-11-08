-- Neon database roles for M1 (D2): `neondb_owner` is the DDL/migration role; `ks_runtime` is the
-- DML-only runtime role for the API and Worker (and the Admin seed job).
--
-- STATUS (2026-11-06): sections 1 to 3 below were EXECUTED against the production Neon database
-- (database `neondb`, PostgreSQL 18.6) as `neondb_owner`, in one transaction, and verified
-- (section 4). Section 5, the `database-url` cutover, was also DONE on 2026-11-06 (see section 5
-- and `docs/milestones/M1/handoff.md`, "Verified on production").
-- Nothing in this file contains a credential.
--
-- Findings that shaped the approach (Neon behavior, observed):
--  * A role created in the Neon console is a member of `neon_superuser` and has CREATEROLE,
--    CREATEDB, REPLICATION and BYPASSRLS. `neondb_owner` has no ADMIN option on it, so it could
--    neither REVOKE that membership nor DROP the role. The console-created role was deleted in the
--    Neon console and recreated with SQL, which does not add `neon_superuser` membership.
--  * Neon's control plane rejects a pre-hashed SCRAM password ("only supports plaintext
--    passwords"). To avoid sending a temporary plaintext password that would immediately need
--    rotation, the role was created NOLOGIN with NO password. LOGIN and a freshly generated
--    password were set at the cutover (section 5).

-- ============================================================================================
-- 1. READ-ONLY inspection (run first). Decides the DDL role.
-- ============================================================================================
SELECT current_user, current_database(), version();

SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;
-- Result: alembic_version, jobs, outbox, spike_vector_probe, all owned by neondb_owner.
-- Decision: neondb_owner is the DDL role (the migration job keeps working with ownership
-- unchanged). Another role cannot ALTER tables it does not own.

SELECT version_num FROM alembic_version;   -- 0001 before the first M1 migration

-- ============================================================================================
-- 2. Create the runtime role BY SQL (not the console): no login, no password, no privileges.
--    Run as neondb_owner.
-- ============================================================================================
CREATE ROLE ks_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

-- ============================================================================================
-- 3. Minimal DML grants, including future M1 tables (executed in the same transaction as 2)
--    The tables are listed explicitly so `alembic_version` is never granted.
-- ============================================================================================
GRANT USAGE ON SCHEMA public TO ks_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON jobs, outbox, spike_vector_probe TO ks_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ks_runtime;

-- Tables created by FUTURE migrations (0002 creates users, sessions, departments, ...) are owned by
-- neondb_owner; without default privileges the runtime role could not see them.
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ks_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO ks_runtime;
-- (No change to PUBLIC or to any other role. TRUNCATE, REFERENCES, TRIGGER are not granted.)

-- ============================================================================================
-- 4. Verification (READ-ONLY; run as neondb_owner). Results recorded 2026-11-06:
--    not superuser, no CREATEROLE/CREATEDB/REPLICATION/BYPASSRLS, rolcanlogin = false,
--    no role memberships (not neon_superuser, pg_read_all_data or pg_write_all_data),
--    no CREATE on the database or on schema public, DML on the three tables, USAGE+SELECT on
--    spike_vector_probe_id_seq, no privilege at all on alembic_version, default ACLs for
--    neondb_owner = {ks_runtime=arwd} on tables and {ks_runtime=rU} on sequences.
--    Note: pg_roles always shows the password column masked, so "no password" followed from the
--    CREATE ROLE statement having none. The state recorded here is from before the cutover:
--    rolcanlogin = false was true then and is no longer true after section 5.
-- ============================================================================================
SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls, rolcanlogin
FROM pg_roles WHERE rolname = 'ks_runtime';

SELECT r.rolname AS member_of
FROM pg_auth_members m
JOIN pg_roles r ON r.oid = m.roleid
JOIN pg_roles u ON u.oid = m.member
WHERE u.rolname = 'ks_runtime';                                    -- expect no rows

SELECT has_schema_privilege('ks_runtime', 'public', 'CREATE')            AS schema_create,    -- false
       has_database_privilege('ks_runtime', current_database(), 'CREATE') AS database_create;  -- false

SELECT t, p, has_table_privilege('ks_runtime', 'public.' || t, p) AS granted
FROM unnest(ARRAY['jobs', 'outbox', 'spike_vector_probe', 'alembic_version']) AS t,
     unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) AS p
ORDER BY t, p;               -- DML true on the first three, TRUNCATE false, alembic_version all false

SELECT defaclobjtype::text AS objtype, defaclacl::text AS acl
FROM pg_default_acl WHERE pg_get_userbyid(defaclrole) = 'neondb_owner';

-- ============================================================================================
-- 5. `database-url` cutover. DONE on 2026-11-06 (kept below as the record of what was run; each
--    step needed the Owner's separate approval). Recorded outcome in
--    `docs/milestones/M1/handoff.md`: a real pooled login as `ks_runtime` passed DML in a
--    rolled-back transaction and was denied CREATE TABLE, ALTER and reading `alembic_version`;
--    `database-url` version 2 is the pooled `ks_runtime` URL (version 1, `neondb_owner`, is
--    preserved for rollback); `migration-database-url` holds the direct `neondb_owner` URL; the
--    live API revision `knowserve-api-00007` runs on the runtime credential.
-- ============================================================================================
--  a) ALTER ROLE ks_runtime LOGIN PASSWORD '<freshly generated, in memory only, never printed>';
--  b) Real login test through the POOLED host ("-pooler"), every statement rolled back:
--       BEGIN; SELECT count(*) FROM jobs;
--              INSERT INTO jobs (job_type, correlation_id) VALUES ('grant_smoke', 'req_grant_smoke');
--       ROLLBACK;
--     and these must be denied: CREATE TABLE, ALTER TABLE jobs, DROP TABLE outbox,
--     TRUNCATE jobs, SELECT * FROM alembic_version, CREATE ROLE.
--     After migration 0002 has run (as neondb_owner through the migration job), repeat the smoke
--     on the new tables (for example SELECT count(*) FROM departments; expect 5).
--  c) Publish from stdin to Secret Manager (never to a file, the repo or CI):
--       migration-database-url : neondb_owner, DIRECT host (not "-pooler")
--       database-url           : ks_runtime, POOLED host ("-pooler"), as a new version
--     The previous `database-url` version was kept enabled until M1-AC11 (the migration job run)
--     had passed, so the runtime could be rolled back.
