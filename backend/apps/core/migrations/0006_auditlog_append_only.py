"""Make `core_auditlog` append-only at the DATABASE, not only in Python.

WHAT THIS BUYS, AND WHAT IT DOES NOT. `AuditLog.save()` already refuses to rewrite a
row, but that fence lives in one method: `QuerySet.update()`, raw SQL, a shell, or any
code that never calls `save()` walks straight past it. The trigger below is the version
that holds against everything reaching this database through a normal connection — the
ORM-level compromise the audit log is actually pointed at (Plan-16 Task 4: the attacker
who is already inside with a key). It does NOT hold against a database superuser, who
can `ALTER TABLE ... DISABLE TRIGGER`, nor against root on the box, who has the data
directory. The runbook sentence is: **audit rows are tamper-RESISTANT against
application-level compromise, not tamper-EVIDENT against root or a DB admin.**

There is deliberately no hash chain. Chaining without an external anchor is theatre —
anybody who can write the table re-chains it in one UPDATE — and it would assert a
guarantee that does not exist. True off-box WORM rides the Plan-22 S3 work (bucket
versioning plus a credential with no delete permission); it is noted there and not
built here.

TWO COLUMNS STAY MUTABLE, and each has exactly one reason:

* `changes` — the GDPR redaction. `apps/accounts/tasks.anonymize_deleted_accounts`
  hollows the VALUES out of rows about a deleted customer and keeps the keys, so both
  promises hold: the data is gone, and the trail still says who touched what and when.
  The residual is stated plainly: an attacker with ORM access can blank the `changes`
  of rows they made. They cannot remove the row, nor change who, when, from where, on
  which session, which object, or which action — and every row is mirrored to the
  `apps.security` stream with its keys and ids, off this database.
* `actor_id` — `on_delete=SET_NULL` on the actor FK issues an UPDATE. That is the
  behaviour that stops a deleted staff account taking its history with it, and
  `actor_email` is an immutable snapshot of the same fact, which is why nulling the FK
  loses nothing.

Every other column, including `created_at` and `id`, is refused. The check compares the
whole row as JSON minus those two, rather than naming columns, so a column added later
is immutable by DEFAULT rather than by somebody remembering to extend a list.

── THE `REVOKE`, AND WHY IT IS HONESTLY LABELLED INERT ──────────────────────────────

The Task 4 ruling also called for `REVOKE UPDATE, DELETE` on this table from the app
role. It is issued below, and **it has no effect in this deployment today**: verified
2026-07-29 against the dev Postgres, `SELECT rolsuper FROM pg_roles WHERE
rolname=current_user` is TRUE — the role Django connects as is a Postgres SUPERUSER,
because the `postgres:16-alpine` image creates `POSTGRES_USER` as one, and
`infra/docker-compose.prod.yml` uses that image the same way. A superuser bypasses all
privilege checks, so the grant layer stops nobody. Empirically confirmed: after the
REVOKE, an UPDATE from the same connection still succeeded.

It is still issued, for two reasons: it costs nothing, and it is the control that goes
LIVE the day the app connects as a least-privilege role, which is a tracked TODO in
`docs/runbooks/admin-gate.md`. It is written down as inert here so that nobody reads
the migration and concludes the table is protected by privileges when it is protected
by the trigger. This codebase has been bitten three times by comments describing
controls nobody built; that is not happening again in a migration.

Postgres only. On SQLite (the `DATABASE_URL`-less fallback for hacking without Docker)
this is a no-op and `AuditLog.save()` is the only fence — stated here rather than left
for somebody to discover.
"""
from django.db import migrations

TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION core_auditlog_append_only() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'core_auditlog is append-only: rows cannot be deleted';
    END IF;
    IF (to_jsonb(NEW) - 'changes' - 'actor_id')
       IS DISTINCT FROM (to_jsonb(OLD) - 'changes' - 'actor_id') THEN
        RAISE EXCEPTION
            'core_auditlog is append-only: only changes and actor_id may be rewritten';
    END IF;
    RETURN NEW;
END;
$fn$;
"""

CREATE_TRIGGER = """
CREATE TRIGGER core_auditlog_append_only
BEFORE UPDATE OR DELETE ON core_auditlog
FOR EACH ROW EXECUTE FUNCTION core_auditlog_append_only();
"""

# Inert while the app role is a superuser — see the module docstring. Written as
# CURRENT_USER so it names whatever role actually runs the migration rather than a
# hard-coded username that would be wrong on somebody else's machine.
REVOKE = """
REVOKE UPDATE, DELETE ON core_auditlog FROM CURRENT_USER;
GRANT UPDATE (changes, actor_id) ON core_auditlog TO CURRENT_USER;
"""

DROP = """
DROP TRIGGER IF EXISTS core_auditlog_append_only ON core_auditlog;
DROP FUNCTION IF EXISTS core_auditlog_append_only();
GRANT UPDATE, DELETE ON core_auditlog TO CURRENT_USER;
"""


def _apply(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(TRIGGER_FUNCTION)
    schema_editor.execute(CREATE_TRIGGER)
    schema_editor.execute(REVOKE)


def _unapply(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(DROP)


class Migration(migrations.Migration):

    dependencies = [("core", "0005_auditlog")]

    operations = [migrations.RunPython(_apply, _unapply)]
