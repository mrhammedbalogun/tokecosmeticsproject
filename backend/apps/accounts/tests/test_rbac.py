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


def test_no_scope_named_view_is_ever_a_write_scope():
    """Naming discipline, enforced. A `.view` scope that mutates state will eventually
    be granted by someone who read the name and believed it — which is how Support
    would have silently acquired the power to transition orders. Anything that writes
    gets a verb: `.operate` (state transitions) or `.manage` (money / destructive).
    """
    writeable_suffixes = (".manage", ".operate")
    for scope in SCOPES:
        assert scope.endswith((".view", *writeable_suffixes)), (
            f"{scope} uses an unrecognised verb; use .view, .operate or .manage"
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
def test_the_four_roles_exist_as_groups_and_nothing_else_does():
    """The seed migration and the scope table must not drift apart: a group with no
    row in the table grants nothing, and a role in the table with no group can never
    be assigned."""
    assert set(Group.objects.values_list("name", flat=True)) == set(ROLES)


@pytest.mark.django_db
def test_reseeding_the_roles_is_a_no_op(django_user_model):
    """The seed migration must survive being replayed against a database that already
    has the groups — production may well be seeded by hand before the migration lands,
    and a second Owner group (or a recreated one) would silently orphan every
    membership attached to the first.
    """
    import importlib

    from django.apps import apps as global_apps

    seed = importlib.import_module("apps.accounts.migrations.0003_seed_admin_roles")
    owner_group = Group.objects.get(name="Owner")
    staff = django_user_model.objects.create_user(
        email="owner@toke.test", password="x", is_staff=True
    )
    staff.groups.add(owner_group)

    seed.seed_roles(global_apps, None)

    assert Group.objects.count() == len(ROLES)
    assert Group.objects.get(name="Owner").pk == owner_group.pk
    assert scopes_for_user(staff) == OWNER


def test_unknown_role_has_no_scopes():
    """A typo'd or deleted group must fail closed, not raise or grant."""
    assert scopes_for_role("Manger") == frozenset()


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
