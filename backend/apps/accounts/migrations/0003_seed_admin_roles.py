"""Seed the four staff roles as Django Groups.

Roles are Groups (Plan-16 design ruling 1), so this migration creates the shape
that `apps/accounts/rbac.py` grants scopes to. It creates GROUPS ONLY and attaches
no `Permission` rows: the scope table in rbac.py is the single source of truth for
what a role can do, and half-populated Django permissions would read like a second,
authoritative answer to the same question while actually governing nothing.

Idempotent (`get_or_create` on the name) so re-running against a database that
already has the groups — including the production database, where the roles may be
seeded before this branch merges — is a no-op that preserves existing memberships.

THE REVERSE IS A DELIBERATE NO-OP, and the reasoning is the whole point of this
docstring. It used to delete the four groups, which read like the honest inverse of
"create these groups" and was not:

* `get_or_create` on names as generic as `Owner`, `Manager`, `Support` and `Content`
  does not only create. It ADOPTS whatever group already carried that name, along
  with its members and its `Permission` rows. The reverse then deleted that group —
  data this migration never created and cannot put back.
* Deleting a group cascades the M2M, so every staff membership in it is destroyed.
  Demonstrated: attach a staff member to `Support`, unmigrate, and the membership is
  gone.
* Down-then-up is worse than down alone, because it looks like it worked. The groups
  come back EMPTY, so every staff account is still `is_staff=True` with zero scopes.
  Nobody notices, because the account anyone tests with is the owner's and
  `rbac.scopes_for_user` short-circuits superusers to everything.

The old rationale — "unmigrating past this point means the scope table is gone too,
so the memberships would grant nothing anyway" — was true and irrelevant. A reverse
migration is normally run to step BACK and then forward again (a bad deploy, a
bisect, a local branch switch), not to abandon the code permanently. Losing who is
who on the way past is not recoverable from anything in this repository.

A reverse that destroys data the forward cannot restore is not a reverse. Leaving
four empty groups behind after an unmigrate costs nothing: they grant nothing without
`rbac.py`, and the forward migration adopts them again on the way back up.
"""
from django.db import migrations

ROLE_NAMES = ["Owner", "Manager", "Support", "Content"]


def seed_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLE_NAMES:
        Group.objects.get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_deletion_requested_at_user_email_verified_at"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    # RunPython.noop, not `None`: a None reverse makes the migration IRREVERSIBLE, so
    # `migrate accounts 0002` becomes a hard error and anyone who needs to step back
    # past this point has to hand-edit django_migrations. The reverse is a no-op
    # because there is nothing safe to undo, not because undoing is forbidden.
    operations = [migrations.RunPython(seed_roles, migrations.RunPython.noop)]
