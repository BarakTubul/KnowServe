-- Local only. The application database (knowserve) is created by POSTGRES_DB.
-- A second, disposable database is used by the automated tests, which drop and recreate its schema.
CREATE DATABASE knowserve_test OWNER knowserve;
