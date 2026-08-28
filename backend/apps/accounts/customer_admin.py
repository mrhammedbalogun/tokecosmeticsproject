"""The staff customer list and detail (Plan-18b). `customers.view`.

── WHY THIS SHIPPED BEFORE PLAN-25 AND NOT AFTER ────────────────────────────────────────

Plan-20's schedule note is explicit: this is *"the densest PII surface in the system and
its detail page is the most IDOR-shaped thing not yet built; shipping it after the
Plan-25 IDOR/PII pass and Plan-26 UAT would put it into production untested against the
class of bug those stages exist to catch."* So it lands between Plan-23 and Plan-25 —
built in time for the hardening pass to actually have something to test.

── WHAT IT DELIBERATELY DOES NOT SHOW ───────────────────────────────────────────────────

Everything on `User` that is not identity or contact. No password hash (not even its
shape), no TOTP secret or recovery codes, no session material. The serializers list fields
explicitly rather than excluding them: `fields = "__all__"` minus a deny-list is one
forgotten field away from publishing a credential, and the field that gets forgotten is
always the one added later.

── LOOKUP IS BY TOKE ID, NOT BY PRIMARY KEY ─────────────────────────────────────────────

`toke_id` ("TK-7X4KQZ") is the customer's public identifier, printed on their order
emails, and is what support is actually holding when they open this page. It is also
~1.5e9 random combinations against a sequential integer — so a scope check that ever
regressed would leak one record to someone guessing, not the whole table. That is defence
in depth, not the defence: `customers.view` is.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Prefetch
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.filters import OrderingFilter, SearchFilter

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.models import Address, LegacyIdentity
from apps.accounts.rbac import HasAdminScope
from apps.analytics.queries import customer_totals, unclaimed_guest_orders
from apps.core.audit import AdminAuditMixin

User = get_user_model()


class CustomerAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        # The REAL column names. `Address` stores free-text city/state as `city_text` and
        # `state_text` (with optional `core.Region` FKs alongside), so a serializer naming
        # `city` builds fine until something forces field construction — which is how this
        # reached a passing test run and was caught by the OpenAPI schema instead.
        fields = [
            "id", "label", "line1", "line2", "landmark", "city_text", "state_text",
            "postcode", "country_code", "is_default_shipping", "is_default_billing",
        ]


class CustomerLegacyIdentitySerializer(serializers.ModelSerializer):
    class Meta:
        model = LegacyIdentity
        fields = ["store", "wp_user_id"]


class CustomerListSerializer(serializers.ModelSerializer):
    """The list row. Contact and status only — no aggregates.

    LTV IS NOT ON THE LIST, on purpose. It is a per-row aggregate query, and a 25-row page
    would fire 25 of them; the top-customers report already answers "who spends most" with
    one grouped query. A number that costs a page-load to show and duplicates a report is
    not worth the N+1.
    """

    name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = [
            "toke_id", "email", "name", "first_name", "last_name", "phone", "whatsapp",
            "is_active", "marketing_consent", "email_verified_at",
            "deletion_requested_at", "date_joined", "last_login", "legacy_source",
        ]


class CustomerDetailSerializer(CustomerListSerializer):
    addresses = CustomerAddressSerializer(many=True, read_only=True)
    legacy_identities = CustomerLegacyIdentitySerializer(many=True, read_only=True)
    totals = serializers.SerializerMethodField()
    unclaimed_guest_orders = serializers.SerializerMethodField()

    class Meta(CustomerListSerializer.Meta):
        fields = CustomerListSerializer.Meta.fields + [
            "addresses", "legacy_identities", "totals", "unclaimed_guest_orders",
        ]

    def get_totals(self, obj) -> list[dict]:
        """Per currency, from `analytics.queries` — never recomputed here.

        Plan-20 put this in the shared layer precisely so that this page and the
        top-customers report cannot drift: they share one `REVENUE_STATUSES`, and a
        customer whose lifetime value disagreed with the report would make both numbers
        untrustworthy without either being obviously wrong.
        """
        return [
            {
                "currency": row["currency_id"],
                "orders": row["orders"],
                "lifetime_value": str(row["lifetime_value"]),
            }
            for row in customer_totals(obj.pk)
        ]

    def get_unclaimed_guest_orders(self, obj) -> int:
        """Orders with this email and no owner — NOT added into `totals`.

        Support's most common question about a migrated customer is "why can't they see
        their old orders", and this is the answer: they have not verified the address yet.
        Summing them into lifetime value would attribute money to somebody who has not
        proved the address is theirs, which is exactly the claim `claims.py` refuses.
        """
        return unclaimed_guest_orders(obj.email)


class CustomerAdminViewSet(AdminAuditMixin, viewsets.ReadOnlyModelViewSet):
    """READ ONLY, and that is a decision rather than a stage this has not reached yet.

    Nothing a staff member needs to *change* about a customer belongs here. Editing an
    email would silently re-point order history and password resets; toggling `is_active`
    is what the deletion flow owns, on a 30-day timer with an anonymisation sweep behind
    it. A write surface here would be a second way to do both, without either's rules.
    Support answers questions from this page; the customer changes their own details.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("customers.view")]
    audit_model_label = "accounts.user"
    # PII-BEARING READS, so GETs are audited. `apps/core/audit.py` draws the line at
    # personal data, and this is the densest such surface in the system: a list row is a
    # real person's name, email and phone, and the detail page adds their addresses and
    # what they have spent. The audit trail is what makes "who looked up this customer"
    # answerable, which is the question that actually gets asked after an incident.
    audit_reads = True
    lookup_field = "toke_id"
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["is_active", "marketing_consent", "legacy_source"]
    search_fields = ["email", "toke_id", "first_name", "last_name", "phone"]
    ordering_fields = ["date_joined", "last_login", "email"]
    ordering = ["-date_joined"]

    def get_serializer_class(self):
        return CustomerDetailSerializer if self.action == "retrieve" else CustomerListSerializer

    def get_queryset(self):
        """THE customer queryset. Global search DERIVES from this view, not from a copy.

        `admin_search.SEARCH_SOURCES` now names this viewset, so the customers section of
        global search runs whatever this returns. That is what Plan-18b's tripwire asked
        for: until this endpoint existed, customers was the one section declaring its own
        scope and queryset by hand.

        A staff-facing list and a staff-facing search that disagree about which customers
        exist is the same bug in two directions — whichever shows more becomes a way around
        the other. Deriving rather than duplicating makes that structural instead of a
        comment, and `test_admin_search` pins the wire by emptying this queryset and
        watching the search section empty with it.

        What it excludes: accounts the deletion sweep has anonymised (shells with nothing
        left to show — listing one would be a deletion promise that was not kept), and
        staff.
        """
        queryset = User.objects.admin_visible().filter(is_staff=False)
        # `getattr`, not `self.action`: global search instantiates this viewset bare to
        # derive the queryset, so `action` is not set on that path. Guarding here rather
        # than making search fake an action keeps the derivation honest — it gets exactly
        # the rows the list would return.
        if getattr(self, "action", None) == "retrieve":
            queryset = queryset.prefetch_related(
                Prefetch("addresses", queryset=Address.objects.order_by("-is_default_shipping", "id")),
                "legacy_identities",
            )
        return queryset
