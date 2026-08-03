"""Report what the CURRENT database connection may do — the runbook's verification
step for the least-privilege role split (Plan-25 task 5), and an honest answer any
other day.

Three facts, each printed with its consequence:
1. superuser?         — a superuser bypasses every privilege check AND can disable
                        the core_auditlog append-only trigger.
2. owns core_auditlog? — an owner can also disable its trigger; the runtime role
                        must not be the owner.
3. can it UPDATE/DELETE audit rows? — tried for real inside a rolled-back
                        transaction, because a grant table can say one thing and
                        the server another (0006 proved that empirically).
"""
from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Report the DB connection's privilege posture against the audit log."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(f"vendor is {connection.vendor}: nothing to check (Postgres only)")
            return

        with connection.cursor() as cur:
            cur.execute("SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)")
            user, superuser = cur.fetchone()
            cur.execute(
                "SELECT tableowner = current_user FROM pg_tables WHERE tablename = 'core_auditlog'"
            )
            row = cur.fetchone()
            owns = bool(row and row[0])

        blocked = {}
        for label, sql in [
            ("UPDATE", "UPDATE core_auditlog SET action = action WHERE FALSE"),
            ("DELETE", "DELETE FROM core_auditlog WHERE FALSE"),
        ]:
            # WHERE FALSE touches no row, so only the PRIVILEGE check can refuse it —
            # the trigger never fires. Rolled back regardless.
            try:
                with transaction.atomic():
                    with connection.cursor() as cur:
                        cur.execute(sql)
                blocked[label] = False
            except Exception:
                blocked[label] = True

        ok = not superuser and not owns and blocked["UPDATE"] and blocked["DELETE"]
        self.stdout.write(f"connected as: {user}")
        self.stdout.write(f"superuser: {superuser}" + ("  <-- can disable the audit trigger" if superuser else ""))
        self.stdout.write(f"owns core_auditlog: {owns}" + ("  <-- can disable the audit trigger" if owns else ""))
        self.stdout.write(f"auditlog UPDATE blocked by privileges: {blocked['UPDATE']}")
        self.stdout.write(f"auditlog DELETE blocked by privileges: {blocked['DELETE']}")
        self.stdout.write(
            "POSTURE: least-privilege ✔" if ok else
            "POSTURE: the trigger is the only fence (expected in dev; fix in prod via "
            "infra/deploy/create-app-role.sql + docs/runbooks/db-least-privilege.md)"
        )
