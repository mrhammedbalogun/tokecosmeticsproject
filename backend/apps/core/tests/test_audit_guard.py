"""The DECLARATION half of the audit guarantee. `test_audit.py` is the behavioural half.

Both halves exist because of what Task 3b found, and that lesson is the reason this
file opens with a warning about itself. Task 3b's surface guard asserted that admin
views DECLARED the right authentication class — and every assertion passed while a
preauth token authenticated the entire customer surface, because stock
`JWTAuthentication` simply never read the claim those views were declaring. **A
declaration test is satisfiable by a class that ignores the thing it declares.**

So nothing here is trusted on its own. Every property this file asserts about a
declaration has a twin in `test_audit.py` that drives one real request and asserts what
actually landed in the database. This file's job is COMPLETENESS — it is the thing that
notices the twenty-eighth admin endpoint added next month — and the behavioural file's
job is TRUTH.

WHAT IS ASSERTED HERE, and why each one is a declaration rather than a behaviour:

1. Every routed admin view mixes in `AdminAuditMixin`. Behaviour cannot establish this
   for endpoints a test does not happen to exercise; the walker can.
2. Every PII-bearing READ opts in to `audit_reads`. Discovered from the scope table, so
   a future `customers.*` endpoint is caught the day it is routed.
3. No allowlisted key names a `write_only` serializer field. This one is a seatbelt for
   a future edit — there is no write-only field on the admin surface today — and it is
   worth having precisely because the day somebody adds one is the day a password could
   land in the audit table.
4. Nothing in production code updates or deletes an audit row except the one named
   redaction function. Static, for the same reason `test_only_totp_confirm_can_mint_an_
   admin_token` is static: it fails on the day the code is written, not on the day
   somebody happens to route it.
"""
import ast
import pathlib

import pytest
from django.urls import get_resolver

from apps.accounts.tests.test_admin_surface_guard import (
    ADMIN_SURFACE,
    ADMIN_URL_PREFIX,
    ADMIN_VIEWS,
    _view_class,
    _walk,
)
from apps.core.audit import AdminAuditMixin

# The scope prefixes whose endpoints serve personal data. `orders.*` carries the
# customer's email, name, phone and both addresses on every row; `customers.*` is in the
# scope table but has no endpoint yet (verified 2026-07-29), which is exactly why this is
# written as a PREFIX RULE rather than a list of view names — the first customers
# endpoint is read-audited by the guard before anybody remembers to ask for it.
PII_SCOPE_PREFIXES = ("orders.", "customers.")

# Views that audit their READS, enumerated. The rule above discovers most of them; this
# list is the second, independent statement, and it is what catches the two directions a
# rule alone misses: a view that opted in for a reason nobody wrote down, and a view
# that quietly opted OUT while still being discovered as PII-bearing.
#
# Each entry says why, because "why is this one audited and that one not" is the only
# interesting question about this list.
READ_AUDITED_VIEWS: dict[str, str] = {
    "AdminGigShipmentView": "the fulfilment panel sits on an order and names its receiver linkage",
    "AdminOrderListView": "the order queue: customer email and address on every row, and the search term is the record",
    "AdminOrderDetailView": "one order in full: name, email, phone, both addresses, payment history",
    "AdminRefundsOwedView": "a list of orders, each with the customer on it",
    "AdminOrderCSVExportView": "bulk egress — every customer's email, country and totals in one file",
    "AdminOrderInvoiceView": "an invoice carries the customer's name, home address and billing details",
    "ProductCSVExportView": "bulk egress — the whole catalogue and every price, in one file",
    "StockCSVExportView": "bulk egress — the whole stock position in one file",
    "AuditLogListView": "returns other people's data in `changes`, and reading it is what precedes editing it",
    "AdminSearchView": "one parameter reaching customers, orders and products at once — the highest-yield PII read on the surface",
    # Plan-20a. Aggregates are not personal data, but a REPORT EXPORT is bulk egress by
    # the same argument as the order export: top-customers names people, and any range
    # can be dumped in one call. The on-screen report is deliberately NOT audited.
    "CustomerAdminViewSet": "the customer list and detail: name, email, phone, addresses and lifetime spend — the densest PII surface on the admin",
    "ReportExportView": "bulk egress — a whole reporting range in one file, and one report names customers",
}


def _audited_views() -> dict[str, type]:
    """Every admin view that carries the mixin, keyed by class name."""
    return {name: cls for name, cls in ADMIN_VIEWS.items() if issubclass(cls, AdminAuditMixin)}


def test_every_admin_view_carries_the_audit_mixin():
    """The completeness check, and the reason this file is not a snapshot.

    A twenty-eighth admin endpoint added next month fails HERE rather than silently
    becoming the one staff action that leaves no trace. `ADMIN_VIEWS` is discovered from
    the live URLconf by `test_admin_surface_guard.py`, so there is no list to forget to
    extend — the surface guard already refuses to let an admin route exist without an
    `ADMIN_SURFACE` entry, and this rides on that.

    The mixin on a view is not by itself proof that a row gets written — that is
    `test_audit.py::test_every_admin_write_endpoint_writes_a_row`, which drives real
    requests. This says every view is IN the mechanism; that one says the mechanism
    works.
    """
    missing = sorted(name for name, cls in ADMIN_VIEWS.items() if not issubclass(cls, AdminAuditMixin))
    assert not missing, (
        f"these admin views do not carry AdminAuditMixin, so anything they do leaves no "
        f"audit row: {missing}"
    )


def _get_routes():
    """(pattern, view_class) for every admin-prefix route exposing a GET."""
    routes = []
    for pattern, _name, callback in _walk(get_resolver()):
        if not pattern.startswith(ADMIN_URL_PREFIX):
            continue
        view_class = _view_class(callback)
        if view_class is None or view_class.__name__ not in ADMIN_SURFACE:
            continue
        actions = getattr(callback, "actions", None)
        methods = (
            {m.lower() for m in actions}
            if actions
            else {m for m in view_class.http_method_names if hasattr(view_class, m)}
        )
        if "get" in methods:
            routes.append((pattern, view_class))
    return routes


def test_every_pii_bearing_read_route_is_audited():
    """Design ruling 4 said reads are not audited. Task 4 REVISED that, and this is why.

    "Support bulk-exported the customer list" is not an edge case on an admin surface —
    it is the canonical insider event an audit log exists for, and a log of writes only
    cannot see it. The original ruling imported an intuition from customer-facing traffic
    (volume, no value) that does not survive contact with a staff population of one.

    Discovered from the SCOPE, not from a list of names: any route with a GET whose view
    holds an `orders.*` or `customers.*` scope must set `audit_reads`. `customers.view`
    exists in the scope table with no endpoint behind it yet, so the first one written
    fails here on the day it is routed rather than whenever somebody re-reads this file.
    """
    offenders = [
        f"{pattern} -> {cls.__name__} ({ADMIN_SURFACE[cls.__name__]})"
        for pattern, cls in _get_routes()
        if (ADMIN_SURFACE[cls.__name__] or "").startswith(PII_SCOPE_PREFIXES)
        and not getattr(cls, "audit_reads", False)
    ]
    assert not offenders, (
        "these routes serve personal data on a GET and write no audit row for it — set "
        f"`audit_reads = True` on the view: {sorted(set(offenders))}"
    )


def test_the_read_audited_set_is_exactly_what_is_declared():
    """The other direction, which a prefix rule alone cannot give.

    The rule above catches a PII endpoint that FORGOT to opt in. It says nothing about a
    view that opted in and then quietly opted back out — `audit_reads = False` on
    `AdminOrderDetailView` would satisfy nothing above except by also failing the rule,
    while `ProductCSVExportView` (a catalogue endpoint, outside the prefix rule) could
    lose its flag in complete silence. Asserting the SET in both directions is what makes
    turning read auditing off a deliberate, reviewed edit.
    """
    actual = {name for name, cls in ADMIN_VIEWS.items() if getattr(cls, "audit_reads", False)}
    assert actual == set(READ_AUDITED_VIEWS), (
        f"read-audited but not declared: {sorted(actual - set(READ_AUDITED_VIEWS))}; "
        f"declared but no longer read-audited: {sorted(set(READ_AUDITED_VIEWS) - actual)}"
    )


@pytest.mark.parametrize("view_name", sorted(_audited_views()))
def test_no_allowlisted_key_is_a_write_only_serializer_field(view_name):
    """**The seatbelt that keeps the allowlist honest.**

    `changes` is built by filtering the request body through an explicit allowlist, and
    that allowlist is the entire answer to "what stops a secret-shaped field being
    stored". Nothing prevents such a key ARRIVING — the body is whatever the caller sent
    — so the only question that matters is whether anybody ever writes it down.

    Write-only fields are the category that would be written down by accident. They exist
    to be SUBMITTED AND NEVER RETURNED, which is the definition of a credential: a
    password, a token, an API key. `validated_data` contains them, `request.data`
    contains them, and a developer adding "record what changed" to a serializer would
    reasonably list every writable field without noticing that one of them is the one
    field that must never be stored anywhere but a hash.

    HONEST SCOPE, so nobody over-reads a green test: there is no `write_only` field
    anywhere on the admin surface today, so this currently passes vacuously. It is here
    for the day that stops being true, and it is mutation-verified — adding a write_only
    field and allowlisting it fails this test.

    It checks against `audit_body_serializers()`, which is why views whose
    `serializer_class` describes the RESPONSE must declare `audit_serializers` pointing
    at the class that really parses the body. A body serializer the guard cannot see is a
    body serializer whose write-only fields nobody checked.
    """
    view = _audited_views()[view_name]()
    allowlist = set(view.resolve_allowlist())
    if not allowlist:
        return
    for serializer_class in view.audit_body_serializers():
        if serializer_class is None:
            continue
        fields = serializer_class().fields
        offenders = sorted(
            key for key in allowlist if key in fields and fields[key].write_only
        )
        assert not offenders, (
            f"{view_name} allowlists write-only field(s) {offenders} on "
            f"{serializer_class.__name__}. A write-only field exists to be submitted and "
            f"never returned, which is what a credential is — it must not be stored in "
            f"AuditLog.changes."
        )


def test_every_audited_view_resolves_a_model_label_or_says_why_not():
    """A row with no `model_label` is a row nobody can search for.

    Every admin view either has a queryset/serializer the label can be derived from, or
    declares `audit_model_label` explicitly. The exception is `AdminMeView`, which audits
    nothing at all — it carries the mixin only so that "not audited" is a recorded
    decision rather than a view somebody forgot (see the class).
    """
    unlabelled = []
    for name, cls in _audited_views().items():
        if name == "AdminMeView":
            continue
        has_label = bool(
            cls.audit_model_label
            or getattr(cls, "queryset", None) is not None
            or getattr(getattr(getattr(cls, "serializer_class", None), "Meta", None), "model", None)
        )
        if not has_label:
            unlabelled.append(name)
    assert not unlabelled, (
        f"these views write audit rows with an empty model_label, which makes them "
        f"unsearchable: {sorted(unlabelled)}"
    )


# ---------------------------------------------------------------------------
# The static half: nothing rewrites this table but the one redaction function.
# ---------------------------------------------------------------------------

# Queryset methods that would mutate or remove rows. `create` and `bulk_create` are
# absent on purpose — inserting is the whole point of the table.
MUTATING_QUERYSET_METHODS = frozenset(
    {"update", "delete", "bulk_update", "update_or_create", "get_or_create", "save"}
)

# The single function permitted to rewrite `changes`, and the single module it lives in.
# Same shape as `test_admin_surface_guard.ADMIN_MINT_CALLER`, for the same reason: an
# invariant that a test enforces is different in kind from one a reviewer is asked to
# remember.
REDACTION_FUNCTION = "redact_audit_values"
REDACTION_MODULE = "apps/core/audit.py"
REDACTION_CALLER = ("apps/accounts/tasks.py", None)

# The SECOND permitted mutation, added by Task 6, pinned the same way and for the same
# reason. `tombstone_expired_search_terms` blanks the typed term in search rows older than
# 90 days; from any other call site it is a way to erase what somebody was looking for
# before anybody noticed. One caller, named — the daily beat task — or it is a finding.
#
# Two entries in this list is the point at which somebody should feel the cost of a third.
RETENTION_FUNCTION = "tombstone_expired_search_terms"
RETENTION_CALLER = "apps/core/tasks.py"


def _python_sources():
    """Every production Python module in the backend, tests and migrations excluded.

    By PATH rather than by allowlist, so a new app is covered automatically. Tests are
    excluded because they legitimately construct and mutate rows to prove the fences
    hold; migrations because a migration is a reviewed schema change, and the one in
    `0006` is the fence itself.
    """
    root = pathlib.Path(__file__).resolve().parents[3]  # backend/
    for path in sorted((root / "apps").rglob("*.py")) + sorted((root / "config").rglob("*.py")):
        parts = set(path.parts)
        if "tests" in parts or "migrations" in parts or path.name.startswith("test_"):
            continue
        yield path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")


def test_no_production_code_updates_or_deletes_an_audit_row():
    """**The append-only invariant, as a property of the code rather than of a habit.**

    `AuditLog.save()` refuses to rewrite a row, but `QuerySet.update()` and
    `QuerySet.delete()` never call it — so "the model is immutable" would be a claim
    about one method rather than about the table. The database trigger in migration
    `0006` is the fence that actually holds; this test is what stops application code
    from even trying, so the trigger never has to be the thing that catches a bug in
    review.

    It walks the AST for any mutating queryset call whose receiver expression mentions
    `AuditLog`, which catches `AuditLog.objects.filter(...).update(...)` and
    `.delete()`. HONEST LIMIT, the same one the admin-mint walker has: assigning the
    queryset to a local variable first would slip past. That is not a way somebody
    writes this by accident, and the trigger is behind it either way.

    Exactly ONE call site is allowed — the GDPR redaction — and it is allowed in exactly
    one module.
    """
    offenders = []
    for relative_path, source in _python_sources():
        if "AuditLog" not in source:
            continue
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in MUTATING_QUERYSET_METHODS:
                continue
            receiver = ast.unparse(node.func.value)
            if "AuditLog" not in receiver:
                continue
            if relative_path == REDACTION_MODULE:
                continue  # the redaction lives here; the next test pins its call site
            offenders.append(f"{relative_path}:{node.lineno} {receiver}.{node.func.attr}()")
    assert not offenders, (
        "audit rows are append-only; these call sites mutate or delete them outside "
        f"{REDACTION_MODULE}: {offenders}"
    )


def test_the_redaction_has_exactly_one_call_site():
    """The complement. The test above proves nothing else rewrites the table; this proves
    the one thing that may is invoked from the one place that should.

    The redaction exists so that deleting a customer removes their data from `changes`
    without removing the row. That is a GDPR obligation discharged by the account-deletion
    sweep — and a function that can blank an audit row's contents is, from any other call
    site, a way to erase evidence. One caller, named, or it is a finding.
    """
    call_sites = []
    for relative_path, source in _python_sources():
        if relative_path == REDACTION_MODULE:
            continue  # its own definition
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name == REDACTION_FUNCTION:
                call_sites.append((relative_path, node.lineno))
    assert len(call_sites) == 1, (
        f"{REDACTION_FUNCTION} blanks the contents of audit rows. It must be called from "
        f"exactly one place — the account-deletion sweep. Found: {call_sites}"
    )
    assert call_sites[0][0] == REDACTION_CALLER[0], (
        f"the audit redaction moved to {call_sites[0][0]}; the only place allowed to "
        f"call it is {REDACTION_CALLER[0]}"
    )


def test_the_search_term_tombstone_has_exactly_one_call_site():
    """The same pin for the second permitted mutation.

    `tombstone_expired_search_terms` exists so that a typed search term — very often
    somebody else's email address — stops being retained after ninety days, while the row
    around it (actor, jti, IP, timestamp, per-type counts) survives indefinitely. Called
    from anywhere else, with a `now=` far in the future, it is a way for the person being
    investigated to blank exactly the field that says what they were hunting for.

    One caller: the daily beat task.
    """
    call_sites = []
    for relative_path, source in _python_sources():
        if relative_path == REDACTION_MODULE:
            continue  # its own definition
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name == RETENTION_FUNCTION:
                call_sites.append((relative_path, node.lineno))
    assert len(call_sites) == 1, (
        f"{RETENTION_FUNCTION} blanks the search term out of audit rows. It must be called "
        f"from exactly one place — the daily beat task. Found: {call_sites}"
    )
    assert call_sites[0][0] == RETENTION_CALLER, (
        f"the search-term tombstone moved to {call_sites[0][0]}; the only place allowed "
        f"to call it is {RETENTION_CALLER}"
    )


def test_the_tombstone_sweep_is_scheduled():
    """A retention control that is not on the beat schedule is a comment.

    This is the cheapest possible check and it is here because the failure mode is
    invisible: the function exists, its tests pass, the docstrings describe a ninety-day
    window, and terms accumulate forever because nothing ever calls it in production.
    """
    from django.conf import settings

    tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert "apps.core.tasks.tombstone_search_terms" in tasks, (
        f"no beat entry runs the search-term tombstone: {sorted(tasks)}"
    )
