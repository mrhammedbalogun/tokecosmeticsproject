"""Staff authorisation: one scope table, four roles, one permission class.

WHY THIS MODULE EXISTS. Plans 05–11 shipped their admin endpoints behind DRF's
`IsAdminUser`, which is a single bit: any `is_staff` account can do everything,
including issue refunds and change the payout bank account. That is fine while
the only staff account is the owner's and catastrophic the moment a second person
gets a login. This module is the boundary that replaces that bit.

THREE DESIGN RULINGS, all Fable 2026-07-28, all deliberate:

1. **Roles ARE Django Groups** (`Owner`, `Manager`, `Support`, `Content`), seeded
   by `migrations/0003_seed_admin_roles.py`. The master spec's `Role(name)` model
   was rejected: Django already ships group membership, admin UI, and an M2M on
   `User`, so a parallel model would be a second source of truth about who is what,
   and the two would drift.
2. **Scopes, not Django `Permission` rows, at the API boundary.** Django's
   permission machinery is per-model CRUD, which does not describe what an admin
   endpoint actually does ("transition an order", "read a report"). The grants
   below are therefore attached to group NAMES and no `Permission` objects are
   created at all — meaning `user.has_perm()` is *not* the authority here,
   `scopes_for_user()` is. Anything that asks Django's permission system about
   admin access will get the wrong answer; ask this module instead.
3. **Views name scopes, never groups.** `HasAdminScope("orders.manage")` is the
   only thing an endpoint declares. Rewriting who holds a scope is then a one-line
   change here rather than a sweep through five view modules, and the table below
   stays readable as the answer to "what can Support actually do?".

NAMING RULE, enforced by a test: **nothing named `.view` may write.** Scopes are read
by humans deciding what to grant, and a `.view` scope that mutates state will
eventually be handed to someone who trusted the name. Every scope therefore ends in
one of three verbs:

* `.view` — genuinely read-only.
* `.operate` — changes state, but not money. Order status transitions live here.
* `.manage` — money, or destructive, or both.

WHAT THE THREE ORDER SCOPES MEAN, because Task 2 has to apply the split consistently
across 18 endpoints:

* `orders.view` — read the queue, read an order, read its timeline. Nothing else.
* `orders.operate` — the SUPPORT DAY JOB: drive the legal status transitions (mark
  shipped, add tracking, mark delivered). This is what master-tokerebuild.md § Plan-16
  means by "Support: orders read+transition".
* `orders.manage` — the MONEY-TOUCHING half: refunds, confirming a bank-transfer
  receipt, editing line items or totals, cancelling. Support does not hold it.

An earlier draft folded `.operate` into `.view` on the grounds that transitions are
Support's normal work. That was rejected: it made "view" a write scope, and the next
person to grant read access to a temp or a contractor would have granted the ability
to mark orders delivered.
"""
from __future__ import annotations

from rest_framework import permissions

# The four seeded roles. Kept as a tuple so it can be iterated in a stable order by
# the seed migration, the tests, and any future staff-admin UI.
ROLES: tuple[str, ...] = ("Owner", "Manager", "Support", "Content")

# scope -> the roles that hold it. THE source of truth; there is no other.
#
# Owner holds everything by construction (see the assertion at the bottom of this
# module): the shop owner must never be locked out of a surface by an oversight in
# a later plan.
#
# `marketing.manage` is SEPARATE from `cms.manage` on purpose, and the reasoning is
# about risk rather than about which plan ships which screen. Coupons and promotions
# are a MONEY lever — discount abuse is a classic insider vector, and a coupon is
# indistinguishable from a payout once it is redeemed. Page content is an INTEGRITY
# concern: wrong, embarrassing, or legally awkward, but it does not move cash. Folding
# them together means neither can ever be granted alone — a copywriter would arrive
# holding discount powers, or a campaign manager could not launch a campaign without
# the right to rewrite the returns policy.
#
# BANNERS ARE FILED UNDER `marketing.manage`, a judgment call: a banner's job is to
# announce a promotion, so a campaign that cannot be announced cannot run, and the
# homepage promo rail is campaign material rather than the legally load-bearing pages
# (terms, privacy, returns) that `cms.manage` exists to protect. It also keeps a
# content editor from overriding a live campaign's placement.
SCOPE_GRANTS: dict[str, frozenset[str]] = {
    "orders.view": frozenset({"Owner", "Manager", "Support"}),
    "orders.operate": frozenset({"Owner", "Manager", "Support"}),
    "orders.manage": frozenset({"Owner", "Manager"}),
    "products.manage": frozenset({"Owner", "Manager"}),
    "customers.view": frozenset({"Owner", "Manager", "Support"}),
    "marketing.manage": frozenset({"Owner", "Manager"}),
    "cms.manage": frozenset({"Owner", "Content"}),
    "reports.view": frozenset({"Owner", "Manager"}),
    # Staff and settings are Owner-only: they are the two surfaces that can escalate
    # privilege or redirect money. Inviting staff mints new administrators; settings
    # covers the payout bank account, which is the single highest-value target in the
    # system (Plan-16 Amendment 1's catastrophic scenario).
    "staff.manage": frozenset({"Owner"}),
    "settings.manage": frozenset({"Owner"}),
}

SCOPES: frozenset[str] = frozenset(SCOPE_GRANTS)


def scopes_for_role(role: str) -> frozenset[str]:
    """Every scope held by one role name.

    Fails CLOSED on an unknown name: a group that was renamed or deleted grants
    nothing, rather than raising a 500 on every admin request.
    """
    return frozenset(scope for scope, roles in SCOPE_GRANTS.items() if role in roles)


def scopes_for_user(user) -> frozenset[str]:
    """The effective scope set for a user — the answer `admin-me/` returns.

    `is_staff` is the gate and it is checked FIRST: group membership on a customer
    account must never grant anything, or a stray group assignment (or a future
    self-service feature that touches `user.groups`) silently mints an admin.

    Superusers short-circuit to everything. That is Django's existing contract for
    `is_superuser` and re-implementing it as "Owner group membership" would create
    exactly the second source of truth ruling 1 rejected.
    """
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    if not getattr(user, "is_staff", False):
        return frozenset()
    if getattr(user, "is_superuser", False):
        return SCOPES
    # One query, names only — this runs on every admin request.
    granted: frozenset[str] = frozenset()
    for name in user.groups.values_list("name", flat=True):
        granted |= scopes_for_role(name)
    return granted


class _BaseAdminScopePermission(permissions.BasePermission):
    """Shared body for the classes `HasAdminScope` builds. Never used directly."""

    scope: str = ""

    def has_permission(self, request, view) -> bool:
        return self.scope in scopes_for_user(request.user)

    def __str__(self) -> str:  # shows the scope in DRF's browsable/debug output
        return f"HasAdminScope({self.scope!r})"


def HasAdminScope(scope: str) -> type[_BaseAdminScopePermission]:  # noqa: N802
    """`permission_classes = [HasAdminScope("orders.manage")]`.

    A FACTORY RETURNING A CLASS, not a class taking an argument, because DRF's
    `APIView.get_permissions` does `[permission() for permission in
    self.permission_classes]` — it instantiates each entry with no arguments. The
    alternatives are an instance that fakes being a class by defining `__call__`
    (works, but every reader has to decode the trick, and it breaks DRF's `&`/`|`
    permission composition), or naming groups in views (ruling 3 forbids it). A
    generated subclass is a real permission class in every respect.

    Deliberately PascalCase: it appears at call sites where a class is expected, and
    reading `HasAdminScope("orders.manage")` as anything else would be misleading.

    An unrecognised scope raises immediately, at import time of the module that
    declares it, so a typo is a startup crash. The alternative failure mode is far
    worse and silent: `HasAdminScope("orders.mange")` would deny everyone except
    superusers forever, and since the owner IS a superuser in this deployment,
    nobody would notice until a staff member complained.
    """
    if scope not in SCOPE_GRANTS:
        raise ValueError(
            f"Unknown admin scope {scope!r}. Known scopes: {sorted(SCOPE_GRANTS)}"
        )
    return type(
        f"HasAdminScope_{scope.replace('.', '_')}",
        (_BaseAdminScopePermission,),
        {"scope": scope},
    )


# Invariants, checked at import so they can never quietly stop being true. A grant
# naming a role the seed migration does not create is dead text, and an Owner missing
# a scope locks the shop owner out of a surface — both are silent failures otherwise,
# and both are cheap to catch here. Raised rather than asserted: `python -O` strips
# asserts, and this is exactly the check that must survive a production start.
for _scope, _roles in SCOPE_GRANTS.items():
    if not _roles <= set(ROLES):
        raise RuntimeError(f"{_scope} is granted to a role that is never seeded: {_roles}")
if scopes_for_role("Owner") != SCOPES:
    raise RuntimeError("Owner must hold every scope")
