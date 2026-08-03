-- Create the least-privilege runtime role (Plan-25 task 5).
--
-- WHY. core/migrations/0006 made core_auditlog append-only with a trigger and
-- honestly labelled its REVOKE inert: Django connects as POSTGRES_USER, which the
-- postgres image creates as a SUPERUSER, and a superuser bypasses every privilege
-- check and can DISABLE TRIGGER besides. This script is what makes that caveat
-- retire: the app starts connecting as toke_app, which is NOT a superuser and NOT
-- the owner of any table — so the trigger cannot be disabled by a compromised app
-- connection, and the auditlog REVOKE finally stops someone.
--
-- The split that results:
--   POSTGRES_USER (owner)  — bootstrap, backups, and `manage.py migrate` at deploy
--                            (DDL needs ownership). Never used by the running app.
--   toke_app (runtime)     — web, celery worker, celery beat. DML on everything,
--                            EXCEPT update/delete on core_auditlog (changes/actor_id
--                            stay updatable: the GDPR redaction and SET_NULL, exactly
--                            as 0006 argues).
--
-- Run ONCE as the owner, with :app_password set (see docs/runbooks/db-least-privilege.md):
--   psql -v app_password="'<generated>'" -f create-app-role.sql
-- Idempotent: re-running refreshes grants and resets the password.

DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'toke_app') THEN
      CREATE ROLE toke_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
   END IF;
END $$;

ALTER ROLE toke_app WITH PASSWORD :app_password;

DO $$ BEGIN
   EXECUTE format('GRANT CONNECT ON DATABASE %I TO toke_app', current_database());
END $$;
GRANT USAGE ON SCHEMA public TO toke_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO toke_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO toke_app;

-- Tables created by FUTURE migrations (which run as the owner) get the same DML
-- automatically — without this, every deploy that adds a table would 500 at runtime.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
   GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO toke_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
   GRANT USAGE, SELECT ON SEQUENCES TO toke_app;

-- The control 0006 wrote as inert, now live against the role that actually connects.
REVOKE UPDATE, DELETE ON core_auditlog FROM toke_app;
GRANT UPDATE (changes, actor_id) ON core_auditlog TO toke_app;
