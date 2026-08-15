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
one of four verbs:

* `.view` — genuinely read-only.
* `.operate` — changes state, but not money. Order status transitions live here.
* `.manage` — money, or destructive, or both.
* `.delete` — removes a record outright, cascades and all. Above `.manage`, and the
  distinction matters at granting time: a `.manage` holder can rewrite or archive a
  thing, only a `.delete` holder can make it stop existing. Granted more narrowly.

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

import functools
import logging

from rest_framework import permissions

from apps.core.log_safety import scrub

_security_logger = logging.getLogger("apps.security")

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
    # Deleting a product outright is a step above managing it: the row takes its
    # variants, prices, stock records and images with it (order lines survive via
    # SET_NULL and their own name snapshot, but the product is gone for good).
    # Archiving already covers "stop selling this", so hard delete is the Owner's
    # alone. Enforced as an inline elevation in ProductAdminViewSet.destroy — the
    # declared class permission stays products.manage (see catalog/admin_views.py).
    "products.delete": frozenset({"Owner"}),
    # Customer product reviews (hide/delete). Its own scope — moderation straddles
    # catalogue and content, and nav.ts asked for "a review-specific scope to point
    # at". Owner + Manager: pulling a customer's words off a product page is shop
    # management, not copywriting, so Content does not hold it.
    "reviews.manage": frozenset({"Owner", "Manager"}),
    "customers.view": frozenset({"Owner", "Manager", "Support"}),
    # THE PRODUCT EDITOR'S VIDEOS TAB DEPENDS ON THIS GRANT: video upload goes through
    # the cms media endpoints (`MediaAssetAdminViewSet`, `marketing.manage`), while the
    # attach is a catalog write (`products.manage`). That reuse is safe only while every
    # `products.manage` holder also holds this scope —
    # `test_admin_videos.py::test_products_manage_holders_can_reach_the_upload_endpoints`
    # pins it, and splitting the grants means building the OR-of-scopes story the
    # `MediaAssetAdminViewSet` docstring defers.
    "marketing.manage": frozenset({"Owner", "Manager"}),
    "cms.manage": frozenset({"Owner", "Content"}),
    "reports.view": frozenset({"Owner", "Manager"}),
    # Staff and settings are Owner-only: they are the two surfaces that can escalate
    # privilege or redirect money. Inviting staff mints new administrators; settings
    # covers the payout bank account, which is the single highest-value target in the
    # system (Plan-16 Amendment 1's catastrophic scenario).
    "staff.manage": frozenset({"Owner"}),
    "settings.manage": frozenset({"Owner"}),
    # REFERRALS SPLIT THREE WAYS, because "look at the queue", "decide a request" and
    # "assert money left the bank" are three different amounts of trust.
    #
    # `referrals.view` — the payout queue, a referrer's ledger, the fraud flags. Support
    # holds it for the same reason it holds `orders.view`: the person answering "where is
    # my commission?" needs to see the answer.
    # `referrals.manage` — approve, reject, block a referrer, write a manual adjustment.
    # Rejection releases commissions back to `available` and an adjustment moves a
    # balance, so this is Manager-and-above, matching `orders.manage`.
    # `referrals.pay` — mark a request PAID: the claim that cash has actually left the
    # company account. Its own scope even though the same roles hold `referrals.manage`,
    # because "we should send this" and "the money went" are different assertions, and
    # splitting them means either grant can change later without dragging the other with
    # it. It is the END of an audit trail rather than a step in it — nothing downstream
    # re-checks it — which is why it is not simply folded into manage.
    #
    # HAMMED'S CALL, 2026-08-15: Manager holds it, not Owner alone. My argument for
    # Owner-only was the `products.delete` parallel; his is operational and it wins — the
    # Manager is who actually runs the monthly bank transfers, and a scope withheld from
    # the person doing the work gets worked around by borrowing the Owner's login, which
    # is strictly worse than granting it. The audit row names whoever clicked, and that is
    # what makes widening this safe.
    "referrals.view": frozenset({"Owner", "Manager", "Support"}),
    "referrals.manage": frozenset({"Owner", "Manager"}),
    "referrals.pay": frozenset({"Owner", "Manager"}),
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

    THE UNKNOWN-GROUP LINE is a data invariant, not a permission decision — the answer
    is still "no scopes", and failing closed stays right. It exists because failing
    closed here is also SILENT: `Group.name` is editable in the Django admin, so
    renaming `Support` to `Customer Support` revokes every scope from everyone in it
    with no exception, no 500, and nothing to trace a complaint back to. Logged at
    ERROR so Sentry raises it as an event at the moment a real person is affected;
    `apps/accounts/checks.py` catches the same condition at deploy time, which is
    earlier but only seen by whoever reads deploy output.

    Deliberately NOT fired for a staff member with no groups at all — that is the
    normal state of a freshly invited account, and alerting on it would train whoever
    reads Sentry to dismiss the alert that matters.
    """
    if not getattr(user, "is_authenticated", False):
        return frozenset()
    if not getattr(user, "is_staff", False):
        return frozenset()
    if getattr(user, "is_superuser", False):
        return SCOPES
    # One query, names only — this runs on every admin request.
    granted: frozenset[str] = frozenset()
    unknown: list[str] = []
    for name in user.groups.values_list("name", flat=True):
        if name not in ROLES:
            unknown.append(name)
        granted |= scopes_for_role(name)
    if unknown:
        _security_logger.error(
            "staff account %s is in group(s) that grant nothing: %s",
            scrub(getattr(user, "email", "<unknown>")),
            scrub(", ".join(sorted(unknown))),
        )
    return granted


class _BaseAdminScopePermission(permissions.BasePermission):
    """Shared body for the classes `HasAdminScope` builds. Never used directly."""

    scope: str = ""

    def has_permission(self, request, view) -> bool:
        return self.scope in scopes_for_user(request.user)

    def __str__(self) -> str:  # shows the scope in DRF's browsable/debug output
        return f"HasAdminScope({self.scope!r})"


@functools.lru_cache(maxsize=None)
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
    nobody would notice until a staff member complained. `lru_cache` does not cache
    exceptions, so that check keeps firing on every call.

    MEMOISED so that one scope always means one class. As first written the factory
    minted a fresh class per call, which made `HasAdminScope("x") is
    HasAdminScope("x")` false and — the part that would have bitten — made
    `HasAdminScope("x") == HasAdminScope("x")` false too. Nothing depended on that,
    but the natural way to write a future guard is
    `assert HasAdminScope("orders.manage") in view.permission_classes`, and it would
    have been silently, permanently False. A guard that can never pass is
    indistinguishable from a guard that never fires. Cheaper to make the obvious
    spelling correct than to leave a comment asking people not to write it.
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
