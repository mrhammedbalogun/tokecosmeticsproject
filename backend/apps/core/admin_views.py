"""The read side of the audit log. One endpoint, `settings.manage`, no UI (Task 7).

WHY `settings.manage` AND NOT A SCOPE OF ITS OWN. An `audit.view` scope would be
granted to exactly the roles that already hold `settings.manage` — Owner, and nobody
else — and a scope nobody can hold independently only adds a lookup. More to the point,
this table records what every other role did, so the person who can read it should be
the person who can change who those roles are; splitting them would let a role audit
itself.

WHY THERE IS NO WRITE SIDE AT ALL. There is no create, update or delete route here and
there never will be: `AuditLog.save()` refuses to rewrite a row, a Postgres trigger
refuses UPDATE of anything but `changes`, and the only permitted mutation in the entire
codebase is the GDPR redaction in `apps/core/audit.redact_audit_values`. An endpoint
that could edit this table would make all three of those pointless.
"""
from django.utils.dateparse import parse_datetime
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from rest_framework.exceptions import ValidationError

from rest_framework import viewsets

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.core.models import AuditLog, BusinessDecisions, Country, StoreSettings
from apps.core.serializers import (
    AuditLogSerializer,
    BusinessDecisionsSerializer,
    TaxCountryAdminSerializer,
    TaxSettingsSerializer,
)


def _as_datetime(value: str, param: str):
    """Parse an `after`/`before` query parameter, or raise a 400.

    Passing the raw string into `created_at__gte=` lets Django's own field validation
    raise `django.core.exceptions.ValidationError` from deep inside the queryset — which
    DRF does not catch, so it surfaces as a **500** and, now that Sentry is live, as an
    error event. A filter value is user input; a bad one is a 400.

    The realistic way to send a bad one is not malice: `+` is a SPACE in a query string,
    so an un-encoded ISO timestamp arrives as `2026-07-30T06:33:52 00:00`. Encode it as
    `%2B` — or just send `Z`. The message says so, because the alternative is somebody
    concluding the endpoint is broken.
    """
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValidationError(
            {
                param: (
                    f"Not a datetime: {value!r}. Use ISO 8601, and percent-encode a "
                    "'+' offset as '%2B' — an un-encoded '+' arrives as a space."
                )
            }
        )
    return parsed


class AuditLogListView(AdminAuditMixin, generics.ListAPIView):
    """GET /api/v1/admin/audit/ — filters: `actor` (email substring), `model`,
    `action`, `object_id`, `after`, `before`.

    READ-AUDITED, deliberately, and it is the one place in the codebase where reading a
    table writes to that same table. Two reasons it is worth the strangeness. This
    endpoint returns other customers' data — `changes` holds whatever an admin edit
    touched — so by the Task 4 rule for PII reads it qualifies on its own merits. And
    "who has been reading the audit log, and what were they searching for" is exactly
    the behaviour that precedes somebody deciding which rows to try to remove.

    It does not recurse: one read makes one row, and that row's `changes` holds the
    query parameters, never the rows returned.

    ORDERING IS NEWEST-FIRST and is declared here rather than on `Meta.ordering`,
    because a default ordering on the model would silently apply to the redaction sweep
    and to every future count as well, for no benefit.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = AuditLogSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["action", "model_label", "object_id"]
    audit_reads = True
    audit_action = "list"

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor").order_by("-created_at", "-pk")
        p = self.request.query_params
        if v := p.get("actor"):
            # Matched against the SNAPSHOT column, not through the FK. The snapshot is
            # the field that survives the actor's account being deleted, so searching it
            # is the only way to find the rows belonging to a staff member who has left
            # — which is precisely when somebody goes looking.
            qs = qs.filter(actor_email__icontains=v)
        if v := p.get("model"):
            qs = qs.filter(model_label__iexact=v)
        if v := p.get("after"):
            qs = qs.filter(created_at__gte=_as_datetime(v, "after"))
        if v := p.get("before"):
            qs = qs.filter(created_at__lte=_as_datetime(v, "before"))
        return qs


class TaxSettingsView(AdminAuditMixin, generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/admin/tax/settings/ — the store-wide master switch.

    `settings.manage` (Owner-only), same reasoning as the payments config: this
    changes what every customer pays, which is not an operational knob. The row is a
    singleton `StoreSettings.load()` creates on first touch, so there is no 404 arm.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = TaxSettingsSerializer
    audit_serializers = (TaxSettingsSerializer,)

    def get_object(self):
        return StoreSettings.load()


class BusinessDecisionsView(AdminAuditMixin, generics.RetrieveUpdateAPIView):
    """GET/PATCH /api/v1/admin/business-decisions/ — the two referral percentages.

    `decisions.manage`, Owner AND Manager — one notch wider than the tax screens next
    door, which are `settings.manage` and Owner-only. The reasoning is in `rbac.py`: tax
    is a legal position, these are a commercial one, and the Manager is who makes it.

    A singleton, so there is no 404 arm and no list route; `BusinessDecisions.load()`
    creates the row from the settings defaults on first touch. Both writes are audited
    with the before and after value, which is the only record of who changed a published
    term and when — the table itself keeps no history, because every number it holds has
    already been snapshotted onto the commissions and orders that used it.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("decisions.manage")]
    serializer_class = BusinessDecisionsSerializer
    audit_serializers = (BusinessDecisionsSerializer,)

    def get_object(self):
        return BusinessDecisions.load()


class TaxCountryAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """GET/PATCH /api/v1/admin/tax/countries/ — the per-market tax knobs.

    GET + PATCH only: markets are created by seed migrations, never from a settings
    screen, and deleting one would orphan every order pointing at it (the FK is
    PROTECT anyway). Inactive markets stay listed — a switched-off market's tax
    config should be inspectable before it is switched back on.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = TaxCountryAdminSerializer
    audit_serializers = (TaxCountryAdminSerializer,)
    queryset = Country.objects.select_related("currency").order_by(
        "-is_default", "is_rest_of_world", "name"
    )
    pagination_class = None  # five markets; a pager would be theatre
    http_method_names = ["get", "patch", "head", "options"]
