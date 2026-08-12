"""The admin scope table — who can do what.

This module is the DOCUMENT OF RECORD for staff authorisation. The matrix below
is written out longhand, per role, rather than derived from `rbac.SCOPE_GRANTS`:
a test that recomputes the thing it is testing proves nothing. If a grant changes
in `rbac.py` a line has to change here too, deliberately, in a diff someone reads.

Roles are Django Groups (Plan-16 design ruling 1) seeded by
`accounts/migrations/0003_seed_admin_roles.py`, so `django_db` alone is enough to
have them exist — the tests never create them.
"""
import pytest
from django.contrib.auth.models import AnonymousUser, Group

from apps.accounts.rbac import (
    ROLES,
    SCOPES,
    HasAdminScope,
    scopes_for_role,
    scopes_for_user,
)

# --- the matrix ---------------------------------------------------------------
# Source: master-tokerebuild.md § Plan-16 — "Owner (all), Manager (orders/products/
# customers/coupons/reports), Support (orders read+transition, customers read),
# Content (CMS only)" — as amended by the controller's rulings of 2026-07-28:
# orders splits three ways (nothing named `view` may write), and coupons move out
# of cms.manage into their own marketing.manage.

OWNER = {
    "orders.view",
    "orders.operate",
    "orders.manage",
    "products.manage",
    "products.delete",  # hard delete is destruction, not management — Owner alone
    "reviews.manage",
    "customers.view",
    "marketing.manage",
    "cms.manage",
    "reports.view",
    "staff.manage",
    "settings.manage",
}
MANAGER = {
    "orders.view",
    "orders.operate",
    "orders.manage",
    "products.manage",
    "reviews.manage",  # hiding a customer review is shop management — see rbac.py
    "customers.view",
    "marketing.manage",  # coupons + banners; NOT cms.manage — see rbac.py
    "reports.view",
}
SUPPORT = {"orders.view", "orders.operate", "customers.view"}
CONTENT = {"cms.manage"}

MATRIX = {"Owner": OWNER, "Manager": MANAGER, "Support": SUPPORT, "Content": CONTENT}


@pytest.mark.parametrize("role", sorted(MATRIX))
def test_role_grants_exactly_its_documented_scopes(role):
    assert scopes_for_role(role) == MATRIX[role]


def test_the_table_covers_every_declared_scope():
    """A scope with no grants is a permanently-403 endpoint waiting to happen."""
    assert set(MATRIX["Owner"]) == set(SCOPES)


def test_owner_holds_every_scope():
    """The invariant that keeps a new scope from silently locking the shop owner out."""
    for scope in SCOPES:
        assert scope in scopes_for_role("Owner"), f"Owner is missing {scope}"


def test_every_scope_ends_in_a_recognised_verb():
    """A STRING-FORMAT check, and nothing more — named for what it does.

    It used to be called `test_no_scope_named_view_is_ever_a_write_scope`, which is
    Amendment 7's headline rule and is NOT what this asserts: a `.view` scope wired
    onto a POST endpoint satisfies every line below. The rule itself needs the
    URLconf, so it lives where the routes are, in
    `test_admin_surface_guard.py::test_nothing_named_view_is_routed_onto_a_writing_method`.
    """
    for scope in SCOPES:
        assert scope.endswith((".view", ".operate", ".manage", ".delete")), (
            f"{scope} uses an unrecognised verb; use .view, .operate, .manage or .delete"
        )


def test_support_can_operate_orders_but_not_touch_the_money():
    """The whole point of the three-way order split, asserted in one place."""
    support = scopes_for_role("Support")
    assert "orders.view" in support
    assert "orders.operate" in support
    assert "orders.manage" not in support


def test_coupons_and_page_content_are_separately_grantable():
    """`marketing.manage` (coupons/promotions — a money lever, and a classic insider
    discount-abuse vector) is deliberately NOT the same scope as `cms.manage` (page
    content — an integrity concern). Conflating them means neither can ever be granted
    without the other: a copywriter would get discount powers, or a campaign manager
    could not launch a campaign without page-edit rights.
    """
    assert "marketing.manage" in scopes_for_role("Manager")
    assert "cms.manage" not in scopes_for_role("Manager")
    assert "cms.manage" in scopes_for_role("Content")
    assert "marketing.manage" not in scopes_for_role("Content")


def test_role_names_match_the_declared_roles():
    assert set(MATRIX) == set(ROLES)


@pytest.mark.django_db
def test_every_role_exists_exactly_once_as_a_group():
    """The seed migration and the scope table must not drift apart: a role in the table
    with no group can never be assigned, and two groups sharing a name would split the
    memberships silently.

    Deliberately scoped to the four names rather than asserting over EVERY Group in the
    database. The previous version did the latter, which made this RBAC test the thing
    that breaks the day an unrelated feature seeds a group of its own — a failure with
    nothing to do with what this file is about, in a file whose name sends the reader
    looking in the wrong place.
    """
    names = list(Group.objects.filter(name__in=ROLES).values_list("name", flat=True))
    assert sorted(names) == sorted(ROLES)


# --- the seed migration -------------------------------------------------------
# These run the migration's own functions against the HISTORICAL app registry — the
# `apps` object Django actually hands a RunPython — rather than the live one. The
# distinction is not pedantry: `apps.get_model` on the live registry returns the real
# model with its real managers and signals, so a migration that only works there
# passes the test and fails at `migrate` time (or vice versa).


def _migration_module():
    import importlib

    return importlib.import_module("apps.accounts.migrations.0003_seed_admin_roles")


def _historical_apps():
    """The registry as of 0003 — what `RunPython` passes its callables."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    loader = MigrationExecutor(connection).loader
    return loader.project_state(("accounts", "0003_seed_admin_roles")).apps


@pytest.mark.django_db
def test_reseeding_the_roles_is_a_no_op(django_user_model):
    """The seed must survive being replayed against a database that already has the
    groups — production may well be seeded by hand before the migration lands, and a
    second Owner group (or a recreated one) would silently orphan every membership
    attached to the first.
    """
    seed = _migration_module()
    owner_group = Group.objects.get(name="Owner")
    staff = django_user_model.objects.create_user(
        email="owner@toke.test", password="x", is_staff=True
    )
    staff.groups.add(owner_group)

    seed.seed_roles(_historical_apps(), None)

    assert Group.objects.filter(name__in=ROLES).count() == len(ROLES)
    assert Group.objects.get(name="Owner").pk == owner_group.pk
    assert scopes_for_user(staff) == OWNER


@pytest.mark.django_db
def test_reversing_the_seed_destroys_nothing(django_user_model):
    """THE DATA-LOSS BUG. `get_or_create` on names as generic as `Owner`, `Manager`,
    `Support` and `Content` ADOPTS any group that already had one of those names,
    together with its members and its Permission rows — and the reverse then deleted
    it. Attaching a member to `Support` and unmigrating destroyed the membership,
    which the forward migration cannot put back.

    Down-then-up is worse than down alone: the groups come back EMPTY, so every staff
    account is still `is_staff=True` with zero scopes. Nobody notices, because the one
    account anybody tests with is the owner's, and `scopes_for_user` short-circuits
    superusers to everything.

    A reverse that destroys data the forward cannot restore is not a reverse. This one
    is a documented no-op, and this test is what keeps it that way.
    """
    support = Group.objects.get(name="Support")
    staff = django_user_model.objects.create_user(
        email="support@toke.test", password="x", is_staff=True
    )
    staff.groups.add(support)

    operation = _migration_module().Migration.operations[0]
    assert operation.reversible, "unmigrating past 0003 must not be a hard error"
    operation.reverse_code(_historical_apps(), None)

    assert Group.objects.filter(name="Support").exists(), "the reverse deleted a role"
    assert Group.objects.get(name="Support").pk == support.pk
    assert list(staff.groups.values_list("name", flat=True)) == ["Support"], (
        "the reverse stripped a staff member's role"
    )
    assert scopes_for_user(staff) == SUPPORT


def test_unknown_role_has_no_scopes():
    """A typo'd or deleted group must fail closed, not raise or grant."""
    assert scopes_for_role("Manger") == frozenset()


# --- a renamed group ----------------------------------------------------------
# Failing closed is right and it is also SILENT, which is the problem. `Group.name` is
# editable in the Django admin with no warning attached, and renaming `Support` to
# `Customer Support` — a completely reasonable-looking tidy-up — revokes every scope
# from everyone in it. No exception, no 500, no log line: their admin simply stops
# having anything in it, and the one person who would notice is a superuser, for whom
# `scopes_for_user` short-circuits to everything.
#
# TWO DETECTORS, deliberately, because they catch it at different moments:
#
# * the system check runs at deploy time (`migrate` and `manage.py check` both run it)
#   and finds the condition whether or not anyone has tried to log in yet;
# * the log line fires at the moment a real person is actually affected, and lands in
#   Sentry, which is the surface someone is watching.
#
# Neither alone is enough: the check is only seen by whoever reads deploy output, and
# the log line cannot fire for a staff member who has already given up and gone home.


@pytest.mark.django_db
def test_the_system_check_is_quiet_when_the_roles_are_intact():
    from apps.accounts.checks import admin_role_groups_check

    assert admin_role_groups_check(None) == []


@pytest.mark.django_db
def test_the_system_check_reports_a_renamed_role_group():
    from apps.accounts.checks import admin_role_groups_check

    Group.objects.filter(name="Support").update(name="Customer Support")

    issues = admin_role_groups_check(None)
    assert [issue.id for issue in issues] == ["accounts.W001"]
    assert "Support" in issues[0].msg


@pytest.mark.django_db
def test_the_system_check_stays_quiet_before_the_tables_exist(monkeypatch):
    """`manage.py migrate` runs system checks BEFORE applying migrations, so on a fresh
    database this check runs against a table that does not exist yet. Raising there
    would make the project unable to bootstrap itself."""
    from django.db.utils import ProgrammingError

    from apps.accounts import checks

    def _explode():
        raise ProgrammingError('relation "auth_group" does not exist')

    monkeypatch.setattr(checks, "_existing_role_names", _explode)
    assert checks.admin_role_groups_check(None) == []


@pytest.mark.django_db
def test_a_staff_member_whose_group_grants_nothing_is_logged(django_user_model, caplog):
    """The data invariant. This is the moment the rename actually costs someone their
    access, and before this line it was the moment nothing at all happened."""
    import logging

    Group.objects.filter(name="Support").update(name="Customer Support")
    user = django_user_model.objects.create_user(
        email="support@toke.test", password="x", is_staff=True
    )
    user.groups.add(Group.objects.get(name="Customer Support"))

    with caplog.at_level(logging.INFO, logger="apps.security"):
        assert scopes_for_user(user) == frozenset()  # still fails closed

    errors = [
        rec
        for rec in caplog.records
        if rec.name == "apps.security" and rec.levelno == logging.ERROR
    ]
    assert errors, "a staff member silently lost every scope and nothing was recorded"
    assert "Customer Support" in errors[0].getMessage()


@pytest.mark.django_db
def test_a_staff_member_with_no_group_at_all_is_not_logged(django_user_model, caplog):
    """The noise check that makes the line above worth having. A freshly created staff
    account with no role yet is a NORMAL state — it is what every invite produces
    before a role is attached — and alerting on it would train whoever reads Sentry to
    ignore the alert that matters."""
    import logging

    user = django_user_model.objects.create_user(
        email="new-hire@toke.test", password="x", is_staff=True
    )
    with caplog.at_level(logging.INFO, logger="apps.security"):
        assert scopes_for_user(user) == frozenset()
    assert not [rec for rec in caplog.records if rec.levelno == logging.ERROR]


# --- scopes_for_user ----------------------------------------------------------


@pytest.mark.django_db
def test_superuser_holds_every_scope_without_any_group(django_user_model):
    root = django_user_model.objects.create_superuser(email="root@toke.test", password="x")
    assert scopes_for_user(root) == set(SCOPES)
    assert root.groups.count() == 0


@pytest.mark.django_db
def test_staff_user_holds_the_union_of_their_groups(django_user_model):
    user = django_user_model.objects.create_user(
        email="two-hats@toke.test", password="x", is_staff=True
    )
    user.groups.add(Group.objects.get(name="Support"), Group.objects.get(name="Content"))
    assert scopes_for_user(user) == SUPPORT | CONTENT


@pytest.mark.django_db
def test_group_membership_grants_nothing_without_is_staff(django_user_model):
    """is_staff is the gate; the group is only the shape of the grant. A customer who
    somehow lands in a Group must not thereby become an administrator."""
    customer = django_user_model.objects.create_user(email="shopper@toke.test", password="x")
    customer.groups.add(Group.objects.get(name="Owner"))
    assert scopes_for_user(customer) == frozenset()


def test_anonymous_holds_no_scopes():
    assert scopes_for_user(AnonymousUser()) == frozenset()


# --- HasAdminScope ------------------------------------------------------------


def _allows(scope, user, rf):
    request = rf.get("/api/v1/admin/anything/")
    request.user = user
    return HasAdminScope(scope)().has_permission(request, view=None)


@pytest.mark.django_db
def test_superuser_is_allowed(rf, django_user_model):
    root = django_user_model.objects.create_superuser(email="root@toke.test", password="x")
    assert _allows("orders.manage", root, rf) is True


@pytest.mark.django_db
def test_staff_in_the_right_group_is_allowed(rf, django_user_model):
    user = django_user_model.objects.create_user(
        email="manager@toke.test", password="x", is_staff=True
    )
    user.groups.add(Group.objects.get(name="Manager"))
    assert _allows("orders.manage", user, rf) is True


@pytest.mark.django_db
def test_staff_in_the_wrong_group_is_denied(rf, django_user_model):
    """Support may read the order queue; it may not hold orders.manage."""
    user = django_user_model.objects.create_user(
        email="support@toke.test", password="x", is_staff=True
    )
    user.groups.add(Group.objects.get(name="Support"))
    assert _allows("orders.view", user, rf) is True
    assert _allows("orders.manage", user, rf) is False


@pytest.mark.django_db
def test_staff_in_no_group_is_denied(rf, django_user_model):
    """A freshly created is_staff account is inert until a role is attached."""
    user = django_user_model.objects.create_user(
        email="new-hire@toke.test", password="x", is_staff=True
    )
    assert _allows("orders.view", user, rf) is False


@pytest.mark.django_db
def test_authenticated_customer_is_denied(rf, django_user_model):
    """A valid storefront access token must not open an admin endpoint."""
    customer = django_user_model.objects.create_user(email="shopper@toke.test", password="x")
    assert _allows("orders.view", customer, rf) is False


def test_anonymous_is_denied(rf):
    assert _allows("orders.view", AnonymousUser(), rf) is False


def test_unknown_scope_fails_loudly_at_definition_time():
    """A typo in a view's scope string must break the import, not silently 403 the
    endpoint forever (or, worse, be spelled the same way in two places and mean
    nothing in either)."""
    with pytest.raises(ValueError):
        HasAdminScope("orders.mange")


def test_the_permission_factory_is_usable_as_a_permission_class(rf):
    """DRF instantiates every entry of permission_classes with no arguments, so
    HasAdminScope("x") has to hand back a CLASS, not an instance."""
    cls = HasAdminScope("orders.view")
    assert isinstance(cls, type)
    assert cls().has_permission  # instantiable with no args, DRF-style


def test_the_same_scope_always_yields_the_same_class():
    """The factory used to mint a FRESH class per call, so `HasAdminScope("x") is not
    HasAdminScope("x")` and, worse, `HasAdminScope("x") != HasAdminScope("x")`.

    Nothing depended on it — but the obvious way to write a future guard is
    `assert HasAdminScope("orders.manage") in view.permission_classes`, and that would
    have silently always been False: a guard that can never pass reads exactly like a
    guard that never fires. Memoising the factory makes the natural spelling correct
    instead of leaving a trap for whoever writes it.
    """
    assert HasAdminScope("orders.manage") is HasAdminScope("orders.manage")
    assert HasAdminScope("orders.manage") != HasAdminScope("orders.view")
    # Memoising must not swallow the typo check — that is the factory's other job.
    with pytest.raises(ValueError):
        HasAdminScope("orders.mange")
