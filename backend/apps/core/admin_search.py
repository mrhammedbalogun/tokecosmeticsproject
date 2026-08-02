"""Global admin search — one box, three sections, one scope check per section.

WHAT THIS ENDPOINT IS FOR. The owner runs a phone-and-bank-transfer shop: a customer rings
up quoting an order number, or an address, or half a product name, and somebody has to
answer in the next five seconds. `/api/v1/admin/search/?q=` is that answer.

── THE RULING THAT SHAPED EVERYTHING BELOW ─────────────────────────────────────────────

**Search may return NOTHING the caller could not obtain from a direct GET they are
authorized to make.**

Plan-16 Task 6 was originally specified as "staff, any scope". That would have been
privilege escalation through a convenience feature. A Content editor holds `cms.manage`
and can reach no order or customer endpoint anywhere on this surface — and would have been
able to type an email into the topbar and read back customer names, toke_ids and order
numbers. Task 2 spent eighteen endpoints establishing that boundary; one search box would
have gone around it.

So each SECTION is gated on the SAME scope as that section's own list endpoint, and a
section the caller cannot hold is silently absent. All sections absent is an empty 200,
not a 403: holding `cms.manage` and using the search box is not an offence, just fruitless
— and a 403 would confirm to a stolen session that the sections exist and are worth
attacking.

── WHY THE SCOPE IS DERIVED AND NOT DECLARED ───────────────────────────────────────────

A parallel `{"orders": "orders.view"}` dict inside this module is precisely how the bypass
comes back: somebody tightens the order list endpoint to `orders.manage` in six months and
search keeps answering on `orders.view`, because nothing forces the two files to be read
together. Each `SearchSource` therefore names the LIST VIEW, and both the scope and the
queryset are read off that view:

* **scope** — from the view's own `permission_classes`, the same objects DRF evaluates on
  a real request to that endpoint. There is no second copy to drift.
* **queryset** — by calling the view's own `get_queryset()`. Whatever the list endpoint
  excludes, search excludes, including exclusions added years from now. A search that
  resurfaces records the list endpoint hides is the same bypass sideways, and this makes
  that structurally impossible rather than a thing to remember.

**THE ONE EXCEPTION, stated plainly: `customers`.** There is no customer list or detail
endpoint anywhere on the admin surface — `customers.view` sits in the scope table with
nothing behind it, and Plan-18 builds the page. So that section has nothing to derive FROM
and declares `customers.view` itself, with a queryset on the User manager
(`User.objects.admin_visible()`) that the future list endpoint is meant to share.
`test_admin_search.py::test_the_customers_section_is_the_only_underived_one_and_it_is_pinned`
asserts that any future `customers.*` endpoint gates on the same scope, so the two cannot
diverge silently — and it also fails the day a customers list view IS routed, which is the
day this exception should be deleted.

── ENUMERATION CONTROLS: PROPORTIONATE HYGIENE, NOT A FENCE ────────────────────────────

Be honest about the threat model. A caller who reaches the customers section ALREADY holds
`customers.view`, which grants the (future) list endpoint with its own filters, and a
caller who reaches orders already holds `orders.view` and the order queue with its `search`
parameter. Search therefore adds very little enumeration power beyond what the scope
already granted. The real oracle risk died with the scope gating; what remains is worth
having anyway, and each piece does one job:

* **Minimum term length 3, enforced HERE.** A client debounce is UX, not a control.
* **Ten results per type, and NO PAGINATION.** This is the important one. It is what stops
  search from *becoming* the export tool. Bulk access must go through the list endpoints,
  where it leaves a distinct and visible audit signature — "listed every order matching
  @gmail.com, 3,400 results" — instead of arriving as a hundred quiet little searches.
* **A term length cap**, because the raw term is stored in an append-only table.

── AUDIT ───────────────────────────────────────────────────────────────────────────────

This is the highest-yield PII read on the surface: one parameter that reaches customers,
orders and products at once. It uses Task 4's read-path mixin unchanged — `audit_reads`
plus the one documented hook, `audit_read_extra` — because search is not a new mechanism,
it is the read the existing mechanism was built for.

The row carries the RAW TERM and the PER-TYPE RESULT COUNTS. Hashing or truncating the
term guts the value: "what did this person search for in the week before they quit" is the
question the log exists to answer, and a hash only ever confirms a suspicion somebody
already holds. The counts are the harvest-detection signal — fifty searches returning ten
customers each tells the whole story without another byte of customer data.

The term's exposure is bounded three ways, and all three are real today:

1. the `apps.security` mirror carries KEYS AND IDS ONLY (see `audit.record_audit`), so the
   term never reaches the log stream or Sentry breadcrumbs — verified by
   `test_the_security_mirror_carries_keys_only_never_the_term`, not assumed;
2. the term is tombstoned after 90 days by `audit.tombstone_expired_search_terms`, leaving
   the row skeleton (actor, jti, IP, timestamp, counts) forever;
3. deleting a customer tombstones any search term containing their exact email or toke_id.
   **Honest residual: a PARTIAL typed prefix of a deleted customer's address will not
   match, and lives out its ≤90 days.** That is a bounded, stated imperfection, and it is
   pinned by a test so nobody can quietly believe otherwise.

── NO LINKS, DELIBERATELY ──────────────────────────────────────────────────────────────

Results carry no URLs. Plans 17/18 build the detail pages; until then a link is a 404 with
extra steps. The fields are inline instead, which is most of the feature anyway: "what is
the status of TC-100123" and "which customer is this email" are answerable from this
payload with no navigation at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from typing import Callable

from django.db.models import Q, QuerySet
from django.http import QueryDict
from rest_framework import permissions
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import scopes_for_user
from apps.accounts.throttling import AdminSearchThrottle
from apps.core.audit import SEARCH_AUDIT_MODEL_LABEL, AdminAuditMixin

# Enforced server-side; see the module docstring for why each number is what it is.
MIN_TERM_LENGTH = 3
MAX_TERM_LENGTH = 100
RESULTS_PER_TYPE = 10

# The verb stored in the audit row. The MODEL LABEL is imported from `apps.core.audit`
# rather than restated here, because the 90-day retention sweep selects on it: two copies
# would mean a rename silently stops the sweep from finding anything, and nothing would
# look wrong.
SEARCH_AUDIT_ACTION = "search"

__all__ = [
    "MAX_TERM_LENGTH",
    "MIN_TERM_LENGTH",
    "RESULTS_PER_TYPE",
    "SEARCH_AUDIT_ACTION",
    "SEARCH_AUDIT_MODEL_LABEL",
    "SEARCH_SOURCES",
    "AdminSearchView",
    "SearchSource",
    "source_queryset",
    "source_scope",
]


# --- deriving from the list endpoints ----------------------------------------


class _UnfilteredRequest:
    """The real request with its query parameters removed, for asking a list view what its
    queryset is *before* any filtering.

    A synthetic request rather than the real one, because the list views read
    `request.query_params` to build their filters and the search request carries `q`. Today
    no list view looks at `q`, so passing the real request would work — and would break
    silently on the day one of them grows a `q` filter of its own, with search quietly
    double-filtering. An empty `QueryDict` makes "no filters" a property rather than a
    coincidence.

    Everything else is proxied through, and `user`/`auth` are carried explicitly rather
    than left to the proxy so that a list view which scopes its queryset per user (none do
    today) gets the right answer instead of an anonymous one.
    """

    def __init__(self, request):
        self._request = request
        self.query_params = QueryDict()
        self.user = request.user
        self.auth = getattr(request, "auth", None)
        self.method = "GET"

    def __getattr__(self, name):
        return getattr(self._request, name)


def _scope_of(view_class) -> str:
    """The scope a view's own permission classes require.

    Reads `.scope` off the classes `HasAdminScope` generates, which is the same attribute
    `test_admin_surface_guard.py` inspects and the same object DRF evaluates on a real
    request to that endpoint. Raises rather than guessing: a list view with no scope (or
    with two) is not something search may pick a default for, and a startup crash is a
    far better failure than a section silently gated on the wrong thing.
    """
    scopes = {
        scope
        for permission in view_class.permission_classes
        if (scope := getattr(permission, "scope", None))
    }
    if len(scopes) != 1:
        raise RuntimeError(
            f"{view_class.__name__} declares {sorted(scopes)} — a search section must "
            f"derive exactly one scope from its list endpoint"
        )
    return scopes.pop()


@dataclass(frozen=True)
class SearchSource:
    """One section of the search response.

    `list_view_path` is a dotted string rather than the class itself so this module can be
    imported without dragging in every admin view module at import time (and without the
    circular imports that would follow — `apps.orders.views` imports from `apps.core`).
    """

    key: str
    #: Where the scope and the base queryset come from. `None` only for `customers`,
    #: which has no endpoint yet; see the module docstring.
    list_view_path: str | None
    #: What matches. Takes the term, returns a `Q`.
    match: Callable[[str], Q]
    #: One result → one JSON-able dict. No URLs; see the module docstring.
    row: Callable[[object], dict]
    #: Declared scope, for the one source that cannot derive it.
    declared_scope: str | None = None
    #: Base queryset, for the one source that has no list view to ask.
    base: Callable[[], QuerySet] | None = None
    #: Applied after the match, before the cap.
    order_by: tuple[str, ...] = ()
    #: Extra prefetching for the fields `row` reads. Kept off the derived queryset's own
    #: definition so the list endpoint is not made to pay for search's display needs.
    prefetch: tuple[str, ...] = field(default_factory=tuple)

    def list_view(self) -> type:
        module_path, _, name = self.list_view_path.rpartition(".")
        return getattr(import_module(module_path), name)


def source_scope(source: SearchSource) -> str:
    """The scope governing one section — derived from its list endpoint where there is one.

    Module-level rather than a method so the tests can call it on a bare source, and so the
    derivation reads as one function somebody can follow end to end.
    """
    if source.list_view_path is None:
        return source.declared_scope
    return _scope_of(source.list_view())


def source_queryset(source: SearchSource, request) -> QuerySet:
    """The section's base rows: exactly what its list endpoint would return unfiltered."""
    if source.list_view_path is None:
        return source.base()
    view = source.list_view()()
    view.request = _UnfilteredRequest(request)
    view.args, view.kwargs = (), {}
    view.format_kwarg = None
    return view.get_queryset()


# --- what each section matches and shows -------------------------------------
#
# MONEY IS SERIALISED AS A STRING, never left as a Decimal. DRF's JSON encoder turns a
# Decimal into a FLOAT, and a float total is a rounding bug waiting for somebody to read it
# off a screen and type it into a bank transfer.


def _order_row(order) -> dict:
    return {
        "number": order.number,
        "legacy_number": order.legacy_number,
        "status": order.status,
        "grand_total": str(order.grand_total),
        "currency": order.currency_id,
        "email": order.email,
        "placed_at": order.placed_at.isoformat(),
    }


def _customer_row(user) -> dict:
    return {
        "toke_id": user.toke_id,
        "email": user.email,
        "name": user.get_full_name(),
        "is_active": user.is_active,
        "date_joined": user.date_joined.isoformat(),
    }


def _product_row(product) -> dict:
    return {
        "name": product.name,
        "slug": product.slug,
        "status": product.status,
        # A handful, not all of them: a product with forty variants would otherwise push
        # the other nine results off the screen.
        "skus": [variant.sku for variant in product.variants.all()[:3]],
    }


def _product_match(term: str) -> Q:
    """Name, or the SKU of any variant — as a SUBQUERY, not as an OR across the join.

    MEASURED, not assumed. `Q(name__icontains=t) | Q(variants__sku__icontains=t)` is the
    obvious spelling and it produces `OR` across a LEFT JOIN, which Postgres cannot satisfy
    from either side's index: it seq-scans the whole variant table every time. With 20k
    products and 60k variants that was 36ms with no indexes at all and 50ms WITH them (the
    extra sort for `DISTINCT` costs more than the indexes save). Rewritten as `id IN
    (SELECT product_id FROM variant WHERE …)` the variant side uses its trigram index and
    the same query is 6.6ms.

    The product-name half still scans, because Postgres will not combine a hashed SubPlan
    with an index scan under an OR — acceptable, and the honest reason is scale rather than
    cleverness: the catalogue is 69 products today and will not plausibly reach six figures,
    while `orders` and `accounts_user` grow without bound and are fully indexed. Revisit by
    splitting into two queries if the catalogue ever gets large.
    """
    from apps.catalog.models import ProductVariant

    return Q(name__icontains=term) | Q(
        pk__in=ProductVariant.objects.filter(sku__icontains=term).values("product_id")
    )


# The sections, in the order they are shown. Orders and customers first because those are
# the questions that arrive by phone; the catalogue is the one somebody browses to.
SEARCH_SOURCES: tuple[SearchSource, ...] = (
    SearchSource(
        key="orders",
        list_view_path="apps.orders.views.AdminOrderListView",
        # Number, legacy number and email: the three things a customer reads off a bank
        # transfer or a WhatsApp message. `legacy_number` carries the 879 migrated NG
        # orders, and somebody quoting one of those is exactly the case search exists for.
        match=lambda term: (
            Q(number__icontains=term)
            | Q(legacy_number__icontains=term)
            | Q(email__icontains=term)
        ),
        row=_order_row,
    ),
    SearchSource(
        key="customers",
        # Plan-18b routed the list this always anticipated, so the scope is DERIVED from
        # it like every other section rather than declared here. `base` stays: the search
        # and the list share one queryset function, which is what stops their exclusions
        # drifting apart.
        list_view_path="apps.accounts.customer_admin.CustomerAdminViewSet",
        match=lambda term: (
            Q(toke_id__icontains=term)
            | Q(email__icontains=term)
            | Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
        ),
        row=_customer_row,
        order_by=("-date_joined", "-pk"),
    ),
    SearchSource(
        key="products",
        list_view_path="apps.catalog.admin_views.ProductAdminViewSet",
        match=_product_match,
        row=_product_row,
        prefetch=("variants",),
    ),
)


# Invariants, checked at import so they cannot quietly stop being true — the same
# arrangement, and the same reasoning, as the assertions at the bottom of
# `apps/accounts/rbac.py`. A source that declares BOTH a list view and a scope of its own
# is the exact shape of the drift this design exists to prevent: the declared one would win
# in a reader's head and the derived one would win at runtime. Raised rather than asserted,
# because `python -O` strips asserts and this must survive a production start.
for _source in SEARCH_SOURCES:
    _derived = _source.list_view_path is not None
    _declared = _source.declared_scope is not None or _source.base is not None
    if _derived == _declared:
        raise RuntimeError(
            f"search source {_source.key!r} must EITHER name a list view (deriving its "
            f"scope and queryset from it) OR declare both a scope and a base queryset — "
            f"never both and never neither"
        )
    if _declared and (_source.declared_scope is None or _source.base is None):
        raise RuntimeError(
            f"search source {_source.key!r} declares one of scope/base without the other"
        )
if len({s.key for s in SEARCH_SOURCES}) != len(SEARCH_SOURCES):
    raise RuntimeError("two search sources share a key; one would hide the other")


def _validate_term(raw) -> str:
    """The term, or a 400. Stripped before measuring, so three spaces are not a search."""
    term = (raw or "").strip()
    if len(term) < MIN_TERM_LENGTH:
        raise ValidationError(
            {"q": f"Type at least {MIN_TERM_LENGTH} characters to search."}
        )
    if len(term) > MAX_TERM_LENGTH:
        raise ValidationError({"q": f"Search terms are limited to {MAX_TERM_LENGTH} characters."})
    return term


class AdminSearchView(AdminAuditMixin, APIView):
    """`GET /api/v1/admin/search/?q=` — grouped results, gated section by section.

    **`IsAdminUser` here is not the Plan-16-era single bit coming back.** It is the
    ADMISSION check — every staff member may use the box — and the authorization happens
    per section inside `get()`, against a scope derived from that section's own list
    endpoint. `ADMIN_SURFACE` records the scope as `None` for exactly this reason, and
    `test_admin_search.py::test_the_scope_matrix` is what makes the arrangement a
    guarantee rather than a claim: it drives a real request per seeded role and asserts the
    exact set of sections that came back.

    `AdminJWTAuthentication` alone, as everywhere on this surface: a staff member's
    customer-door token is not a caller with the wrong scopes, it is not a caller (401).

    **THROTTLE: ~60/min, request-counted, keyed on the USER.** Every other lesson on this
    branch says a request-counting cap becomes a denial button — and every one of those
    concerned a SHARED or FORGEABLE key. `admin_login_ip` is one bucket for the whole staff
    because the BFF calls the API server-side, so an anonymous stranger could fill it and
    lock everybody out. This key is neither shared nor forgeable: it comes from the
    validated admin token, so the only person a caller can throttle is themselves, for a
    minute. Do not "fix" this into a failure-counting throttle — there is no failure to
    count, and a search endpoint with no volume cap at all is how a ten-result cap gets
    turned back into an export tool.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [permissions.IsAdminUser]
    throttle_classes = [AdminSearchThrottle]
    # READ-AUDITED, and the endpoint that most needs it: one parameter reaching customers,
    # orders and products at once. `audit_read_extra` adds the per-type counts.
    audit_reads = True
    audit_action = SEARCH_AUDIT_ACTION
    audit_model_label = SEARCH_AUDIT_MODEL_LABEL

    def get(self, request):
        term = _validate_term(request.query_params.get("q"))
        held = scopes_for_user(request.user)

        results: dict[str, list[dict]] = {}
        for source in SEARCH_SOURCES:
            if source_scope(source) not in held:
                continue  # silently absent — see the module docstring
            queryset = source_queryset(source, request).filter(source.match(term))
            if source.order_by:
                queryset = queryset.order_by(*source.order_by)
            if source.prefetch:
                queryset = queryset.prefetch_related(*source.prefetch)
            # `distinct()` is insurance, not a fix for anything today: no source's match
            # currently spans a join (the SKU half of `_product_match` is a subquery
            # precisely so it does not). It is kept because the failure it prevents is
            # SILENT — a joined match returns a product once per matching variant and each
            # duplicate eats one of the ten slots, so the section looks short rather than
            # wrong. Cheap at a cap of ten.
            rows = list(queryset.distinct()[:RESULTS_PER_TYPE])
            results[source.key] = [source.row(obj) for obj in rows]

        # Stashed for the audit hook rather than recomputed: the counts must describe the
        # response that was actually sent, including the sections that were omitted.
        self._counts = {key: len(rows) for key, rows in results.items()}
        return Response(results)

    def audit_read_extra(self, response) -> dict:
        """Per-type result counts, the harvest-detection half of the row.

        Only the sections the caller could SEE appear, which is itself part of the record:
        the row says what this role was shown, so a later reader does not have to
        reconstruct the scope table as it stood on the day.
        """
        return {"counts": getattr(self, "_counts", {})}
