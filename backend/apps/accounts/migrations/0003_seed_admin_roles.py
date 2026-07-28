"""Seed the four staff roles as Django Groups.

Roles are Groups (Plan-16 design ruling 1), so this migration creates the shape
that `apps/accounts/rbac.py` grants scopes to. It creates GROUPS ONLY and attaches
no `Permission` rows: the scope table in rbac.py is the single source of truth for
what a role can do, and half-populated Django permissions would read like a second,
authoritative answer to the same question while actually governing nothing.

Idempotent (`get_or_create` on the name) so re-running against a database that
already has the groups — including the production database, where the roles may be
seeded before this branch merges — is a no-op that preserves existing memberships.

The reverse deletes the four groups, which also drops every staff membership in
them (Django cascades the M2M). That is the honest inverse of "create these groups"
and it is safe in the direction it runs: unmigrating past this point means the
scope table is gone too, so the memberships would grant nothing anyway. Users are
never touched — only the groups.
"""
from django.db import migrations

ROLE_NAMES = ["Owner", "Manager", "Support", "Content"]


def seed_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLE_NAMES:
        Group.objects.get_or_create(name=name)


def unseed_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLE_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_deletion_requested_at_user_email_verified_at"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(seed_roles, unseed_roles)]
