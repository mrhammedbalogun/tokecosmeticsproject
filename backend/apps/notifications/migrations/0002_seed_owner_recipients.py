"""Subscribe the Owner to every registered event.

WHY SEED AT ALL. `resolve_recipients()` has no silent fallback on purpose (see its
docstring), so a fresh table means every event mails nobody — which is precisely the
DEFAULT_FROM_EMAIL bug this feature exists to fix, reborn as an empty screen. Seeding
makes the safety net a VISIBLE row the Owner can see and delete, rather than an invisible
branch in the send path.

THE OWNER GROUP, NOT `is_superuser` AND NOT A HARDCODED ADDRESS. Roles are Groups in this
codebase (`apps/accounts/rbac.py` ruling 1), the Owner group is seeded by
`accounts/0003_seed_admin_roles.py`, and asking the group is the only source of truth that
survives the Owner changing their email or a second Owner being added. A hardcoded
address would be a fourth copy of a fact the database already holds.

IDEMPOTENT and non-fatal. `get_or_create` on the pair, and an empty Owner group is a
no-op rather than an error: a fresh developer database has no staff at all, and a
migration that refuses to apply there would block every `manage.py migrate` on a clean
checkout.

REVERSIBLE. The reverse deletes (seeded-event, Owner-member) rows — which is narrower
than `NotificationRecipient.objects.all().delete()`, the version that would take an
operator's hand-added recipients with it, but WIDER than "only the exact rows this
seeded": it also removes a row somebody added by hand for an Owner on one of these four
events, and it will miss a seeded row whose user has since left the Owner group. Storing
the seeded pks would make it exact; that is not worth a second state table for a reverse
that runs approximately never, so the imprecision is stated here instead of hidden.

The event list is COPIED here rather than imported from `apps/notifications/events.py`.
Migrations are historical records: importing the live registry would make this file's
behaviour change every time an event is added, so re-running it on a rebuilt database
would seed a different set than it did originally. New events are seeded by their own
migration, or left to the operator — this is the standard Django rule and the reason the
ORM hands us a frozen `apps` registry rather than the real models.
"""
from django.db import migrations

SEEDED_EVENTS = (
    "order.paid",
    "order.awaiting_transfer",
    "inventory.low_stock",
    "delivery.gig_wallet_low",
)


def seed(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    NotificationRecipient = apps.get_model("notifications", "NotificationRecipient")

    owner = Group.objects.filter(name="Owner").first()
    if owner is None:
        return

    for user in owner.user_set.filter(is_active=True, is_staff=True):
        for event in SEEDED_EVENTS:
            NotificationRecipient.objects.get_or_create(
                event=event, user=user, defaults={"email": ""}
            )


def unseed(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    NotificationRecipient = apps.get_model("notifications", "NotificationRecipient")

    owner = Group.objects.filter(name="Owner").first()
    if owner is None:
        return

    NotificationRecipient.objects.filter(
        event__in=SEEDED_EVENTS, user__in=owner.user_set.all()
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0001_initial"),
        # The Owner group must exist before we can read its membership.
        ("accounts", "0003_seed_admin_roles"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
