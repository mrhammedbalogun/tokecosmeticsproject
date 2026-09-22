"""The programme admin. TWO surfaces behind two scopes, on purpose.

* **The intake switch** — `entrepreneurship.manage`. Whether the public form is there,
  and what stands in its place. Operational content: wrong is embarrassing, but it names
  nobody and moves no money.

* **The applications** — `entrepreneurship.applications.manage`, and their READS ARE
  AUDITED. Every row is a named student's email, phone number, school and course.
  `apps/core/tests/test_audit_guard.py` enforces the flag by matching the scope PREFIX,
  which is the whole reason the applications scope has its own name rather than sharing
  `entrepreneurship.manage`.

  Deleting one elevates again, to `entrepreneurship.applications.delete` (Owner only).
  Inline, like `ProductAdminViewSet.destroy` and the careers equivalent, so the declared
  `permission_classes` stays the truth the surface guard reads.

── WHY THE SWITCH IS NOT AN ACTION ON THE APPLICATIONS VIEWSET ────────────────────

It would have inherited the PII scope, and therefore `audit_reads` — writing an audit
row every time somebody looks at a boolean, which trains whoever reads the log to skim
it. The careers board hit the mirror image of this with its `stats` endpoint and solved
it the other way (fold in, inherit); here the honest answer is the opposite, because
this endpoint genuinely belongs to a different grant. `entrepreneurship.manage` can be
given to whoever runs the programme without also handing them every applicant.
"""
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import exceptions, generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope, scopes_for_user
from apps.core.audit import AdminAuditMixin
from apps.entrepreneurship import services
from apps.entrepreneurship.admin_serializers import (
    ProgramApplicationDetailSerializer,
    ProgramApplicationListSerializer,
    ProgramApplicationWriteSerializer,
    ProgramSettingsSerializer,
)
from apps.entrepreneurship.filters import ProgramApplicationFilter
from apps.entrepreneurship.models import ProgramApplication, ProgramSettings


class ProgramSettingsAdminView(AdminAuditMixin, generics.RetrieveUpdateAPIView):
    """GET/PATCH `/api/v1/admin/entrepreneurship/settings/` — is the intake open.

    A singleton, so there is no 404 arm and no list route; `ProgramSettings.load()`
    creates the row on first touch. Same shape as the tax, marketing and
    business-decision screens.

    NOT read-audited, deliberately. It holds a boolean and a sentence shown to the
    public — no personal data at all — and the endpoint sits outside the
    `entrepreneurship.applications.` prefix precisely so the guard does not drag it in.
    Both WRITES are audited with the before and after value, which is the record that
    matters: who closed the intake, and when.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("entrepreneurship.manage")]
    serializer_class = ProgramSettingsSerializer
    audit_serializers = (ProgramSettingsSerializer,)

    def get_object(self):
        return ProgramSettings.load()


class ProgramApplicationAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """The students who applied. READ-AUDITED — see the module docstring.

    NO CREATE ROUTE. An application is written by a member of the public through the
    anonymous form and by nothing else; a staff-side create would produce a row nobody
    consented to, with a `submission_count` that means nothing and an email address
    typed by somebody who is not its owner.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("entrepreneurship.applications.manage")]
    audit_reads = True
    audit_serializers = (ProgramApplicationWriteSerializer,)
    filter_backends = [DjangoFilterBackend]
    filterset_class = ProgramApplicationFilter
    http_method_names = ["get", "patch", "delete", "head", "options"]
    queryset = (
        ProgramApplication.objects.select_related("country", "reviewed_by")
        .order_by("-created_at", "-id")
    )

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return ProgramApplicationWriteSerializer
        if self.action == "list":
            return ProgramApplicationListSerializer
        return ProgramApplicationDetailSerializer

    def perform_update(self, serializer):
        """Stamp the reviewer only when the STATUS moved.

        "Reviewed by" answers "who decided", and fixing a typo in the notes is not a
        decision. Comparing against the pre-save value is the only way to tell — a PATCH
        carrying the status it already had is a no-op, not a review.
        """
        before = serializer.instance.status
        application = serializer.save()
        if application.status != before:
            services.mark_reviewed(application, self.request.user)
            application.save(update_fields=["reviewed_by", "reviewed_at", "updated_at"])

    def destroy(self, request, *args, **kwargs):
        """PERMANENT. This is what "please delete my data" resolves to.

        Elevates above the viewset's `entrepreneurship.applications.manage` floor to
        `entrepreneurship.applications.delete` (Owner only) — inline, so the declared
        class permission stays the truth the surface guard reads. Checked BEFORE the
        object lookup, so an unauthorised caller gets a clean 403 rather than a 404 that
        tells them whether the id exists.
        """
        if "entrepreneurship.applications.delete" not in scopes_for_user(request.user):
            raise exceptions.PermissionDenied(
                "Deleting an application requires the "
                "entrepreneurship.applications.delete scope, which only the Owner holds."
            )
        application = self.get_object()
        # Snapshot for the audit row BEFORE anything is destroyed. Deliberately NOT the
        # student's name, email or phone: the audit log is read by more people than this
        # screen is, and a deletion must not be the thing that copies personal data into
        # a table nobody thought of as holding it.
        self._deleted = {
            "id": application.pk,
            "institution": application.institution,
            "status": application.status,
            "applied_at": application.created_at.isoformat(),
        }
        application.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _changes(self, response) -> dict:
        changes = super()._changes(response)
        if self.request.method.upper() == "DELETE" and hasattr(self, "_deleted"):
            changes["deleted"] = self._deleted
        return changes

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Counts for the screen's filter chips.

        AN ACTION ON THIS VIEWSET RATHER THAN A VIEW OF ITS OWN, and that is a decision
        the audit guard made for the careers board first. Written separately it would
        declare `entrepreneurship.applications.manage`, which `PII_SCOPE_PREFIXES`
        matches — so the guard would demand `audit_reads` on an endpoint returning
        nothing but integers, and then `READ_AUDITED_VIEWS` would need an entry
        explaining why a count is personal data. Folded in here it inherits the scope,
        the auditing and the queryset, and there is one less place for the two to drift.
        """
        rows = (
            ProgramApplication.objects.values("status")
            .order_by("status")
            .annotate(count=Count("id"))
        )
        by_status = {row["status"]: row["count"] for row in rows}
        return Response({
            "by_status": by_status,
            "total": sum(by_status.values()),
            # "Needs a decision" is the number the screen leads with: everything nobody
            # has triaged yet.
            "new": by_status.get("new", 0),
            # `annotate` AFTER `values` and `order_by` LAST, which is the only sequence
            # that groups by country rather than by the model's default ordering — a
            # `values().order_by(...).annotate(...)` chain silently adds the ordering
            # field to the GROUP BY and returns one row per application.
            "by_country": list(
                ProgramApplication.objects.values("country_id", "country__name")
                .annotate(count=Count("id"))
                .order_by("-count", "country__name")
            ),
        })
