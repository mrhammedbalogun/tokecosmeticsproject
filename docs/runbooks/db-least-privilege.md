# Applying the least-privilege DB role in production (Plan-25 task 5)

Retires the caveat `core/migrations/0006` wrote about itself: today Django connects as
`POSTGRES_USER`, which the postgres image creates as a SUPERUSER, so the audit log's
append-only REVOKE stops nobody and the trigger is the only fence. After this runbook,
the running app connects as **`toke_app`** — no superuser, no table ownership, no
UPDATE/DELETE on `core_auditlog` (the GDPR `changes`/`actor_id` columns stay updatable)
— and `POSTGRES_USER` is used only by deploy-time migrations and backups.

**Verified end-to-end against the dev Postgres 2026-08-03**: role created by the script,
`check_db_privileges` reports `POSTURE: least-privilege ✔`, normal DML and the redaction
path work, audit UPDATE/DELETE refused by privileges.

Zero-downtime? Near enough: one `docker compose up -d web worker beat` restart.
Rollback at any step: put the old `DATABASE_URL` back and restart.

## Steps (on the VPS)

1. **Generate a password** and add BOTH lines to `/opt/tokecosmetics/.env.prod`:

   ```
   # runtime (least-privilege). MIGRATE_ keeps the owner DSN for deploy-time DDL.
   DATABASE_URL=postgres://toke_app:<generated>@postgres:5432/<dbname>
   MIGRATE_DATABASE_URL=postgres://<POSTGRES_USER>:<POSTGRES_PASSWORD>@postgres:5432/<dbname>
   ```

   (Keep the old `DATABASE_URL` value in a comment for the rollback.)

2. **Create the role** (idempotent; re-run any time to refresh grants):

   ```
   cd /opt/tokecosmetics/app/infra
   docker compose -f docker-compose.prod.yml exec -T postgres \
     psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -v app_password="'<generated>'" -f - < deploy/create-app-role.sql
   ```

3. **Restart the app containers**: `docker compose -f docker-compose.prod.yml up -d web worker beat`

4. **Verify** — both of these, and keep the output with the security-review evidence:

   ```
   docker compose -f docker-compose.prod.yml exec -T web python manage.py check_db_privileges
   #  -> POSTURE: least-privilege ✔
   curl -sf https://api.tokecosmetics.com/healthz/
   ```

   Then click one admin write (a product edit, a note) and confirm an `AuditLog` row
   still lands — INSERT must still work; only rewriting history is refused.

5. **Deploys keep working unchanged**: `deploy.sh` now runs migrations under
   `MIGRATE_DATABASE_URL` when it is set (owner DSN, DDL-capable) and falls back to
   `DATABASE_URL` when it is not — so this runbook can be applied before or after any
   deploy, in either order.

## What this does and does not buy (0006's sentence, upgraded)

Audit rows are now tamper-resistant against an application-level compromise **including
privilege checks**, not only the trigger: a hijacked app connection cannot disable the
trigger (not owner, not superuser) and cannot UPDATE/DELETE the table (revoked). Still
NOT tamper-evident against the DB owner role, a Postgres superuser, or root on the box —
that is the S3 off-box copy's job (bucket versioning, Plan-25 task 7).
