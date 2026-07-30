"""Deploy-time visibility: do the four staff role groups still exist, by name?

WHY THIS EXISTS. Roles are Django Groups (Plan-16 design ruling 1) and `rbac.py`
grants scopes to group NAMES. `Group.name` is an ordinary editable field in the
Django admin, so renaming `Support` to `Customer Support` — an entirely
reasonable-looking tidy-up, done by someone with no reason to suspect it matters —
silently revokes every scope from everyone in that group.

Silently is the operative word. `scopes_for_role` fails CLOSED, which is the right
behaviour and the reason nothing goes wrong loudly: no exception, no 500, no 403 that
anyone can trace back to a cause. The affected staff member's admin simply stops
having anything in it. The one person who would notice first is the owner, and he is
a superuser, for whom `scopes_for_user` short-circuits to every scope.

WHY A SYSTEM CHECK rather than only a runtime signal. Django runs checks during
`manage.py check` AND at the start of `migrate`, so this fires at deploy time — while
someone is watching output and before anybody discovers it by being locked out. It
also detects the condition for staff who have not tried to log in yet, which a
request-time detector by definition cannot. `rbac.scopes_for_user` carries the
complementary runtime line for the moment a real person is actually affected.

WARNING, not ERROR, following payments.W001: an ERROR would abort `migrate`, and the
one moment this is guaranteed to be "wrong" is the fresh database that has not run
the seed migration yet — which is exactly when `migrate` most needs to work.
"""
from django.core.checks import Warning, register
from django.db.utils import OperationalError, ProgrammingError

from apps.accounts.rbac import ROLES


def _existing_role_names() -> set[str]:
    """The role names that currently exist as Groups. Its own function so the tests
    can make the database fail without faking a whole connection."""
    from django.contrib.auth.models import Group

    return set(Group.objects.filter(name__in=ROLES).values_list("name", flat=True))


@register()
def admin_role_groups_check(app_configs, **kwargs):
    try:
        existing = _existing_role_names()
    except (OperationalError, ProgrammingError):
        # DB not migrated yet (fresh checkout / first `migrate`) — nothing to say.
        return []

    missing = [name for name in ROLES if name not in existing]
    if not missing:
        return []
    return [
        Warning(
            "Staff role group(s) missing: " + ", ".join(missing) + ".",
            hint=(
                "apps/accounts/rbac.py grants scopes by group NAME, and a name it does "
                "not recognise grants nothing — silently. Anyone in a renamed group has "
                "lost every admin scope. Rename the group back in Django admin (this is "
                "usually a rename, not a deletion: Group.name is editable there), or "
                "re-run the accounts.0003 seed if it was deleted, then re-attach members."
            ),
            id="accounts.W001",
        )
    ]
