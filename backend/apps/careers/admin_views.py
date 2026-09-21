"""Careers admin (Plan-45). TWO surfaces behind two scopes, on purpose.

* **Postings** — `careers.manage`. Ordinary content management: write the advert, open
  it, close it, archive it. Same three-state visibility model as the store directory, and
  DELETE archives rather than removes, for a stronger reason than the stores one:
  `JobApplication.job` is PROTECTed, so purging a posting would mean purging the people
  who applied to it.

* **Applications** — `careers.applications.manage`, and their READS ARE AUDITED. This is
  the densest personal data in the system (a named stranger's email, phone, CV and
  cover letter), and `apps/core/tests/test_audit_guard.py` enforces the flag by matching
  the scope prefix — which is the whole reason the applications scope has its own name
  rather than sharing `careers.manage`.

  Deleting one elevates again, to `careers.applications.delete` (Owner only), because it
  takes the CV out of the bucket permanently. Inline, like `ProductAdminViewSet.destroy`,
  so the declared `permission_classes` stays the truth the surface guard reads.

── THE RESUME NEVER PASSES THROUGH THIS PROCESS IN PRODUCTION ─────────────────────

`resume` answers with a short-lived presigned S3 URL, not with bytes. Three reasons, and
the third is the one that decided it: the API has three sync workers shared with
checkout; a presigned URL cannot be re-used after a minute, whereas a streamed response
is as long-lived as the tab it opened in; and serving somebody's uploaded file from
`admin.tokecosmetics.com` would put attacker-supplied content on the admin's own origin.
The filesystem fallback in dev streams, because there is nothing to presign against.
"""
from django.db.models import Count, Q
from django.http import FileResponse
from django.core.files.storage import default_storage
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import exceptions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope, scopes_for_user
from apps.careers import resume_storage, services
from apps.careers.admin_serializers import (
    JobApplicationDetailSerializer,
    JobApplicationListSerializer,
    JobApplicationWriteSerializer,
    JobPostingAdminSerializer,
)
from apps.careers.filters import JobApplicationFilter, JobPostingFilter
from apps.careers.models import JobApplication, JobPosting
from apps.cms.s3_uploads import rfc5987_filename
from apps.core.audit import AdminAuditMixin


class JobPostingAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("careers.manage")]
    serializer_class = JobPostingAdminSerializer
    audit_serializers = (JobPostingAdminSerializer,)
    filter_backends = [DjangoFilterBackend]
    filterset_class = JobPostingFilter
    lookup_field = "slug"
    queryset = (
        JobPosting.objects.select_related("country")
        .prefetch_related("locations")
        # Counted here rather than fetched: the postings screen shows "6 applications" on
        # a row and must never be a path to the applications themselves, which sit behind
        # a different scope. A number is not personal data; a list of names is.
        .annotate(application_count=Count("applications", distinct=True))
        .order_by("sort_order", "-published_at", "-id")
    )

    def get_queryset(self):
        """Archived postings are out of sight unless asked for.

        LIST ONLY — applying it to detail routes would leave `restore` unable to find the
        very rows it exists to restore. Same shape, same reason, as
        `apps.stores.admin_views.StoreLocationAdminViewSet.get_queryset`.
        """
        queryset = super().get_queryset()
        if self.action == "list" and not self.request.query_params.get("status"):
            queryset = queryset.filter(archived_at__isnull=True)
        return queryset

    def destroy(self, request, *args, **kwargs):
        """Archive, do not delete. 204 either way, so the client needs no special case.

        Snapshotted into the audit row first: `changes` is normally built from the request
        body, which a DELETE has none of, so without this the trail would prove only that
        *something* was archived.
        """
        posting = self.get_object()
        self._archived = {
            "id": posting.pk, "slug": posting.slug, "title": posting.title,
            "application_count": posting.applications.count(),
        }
        if posting.archived_at is None:
            posting.archived_at = timezone.now()
            posting.save(update_fields=["archived_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _changes(self, response) -> dict:
        changes = super()._changes(response)
        if self.request.method.upper() == "DELETE" and hasattr(self, "_archived"):
            changes["archived"] = self._archived
        return changes

    @action(detail=True, methods=["post"])
    def restore(self, request, slug=None):
        """Bring an archived posting back, AS A DRAFT.

        Deliberately not straight back onto the careers page: it was archived for a
        reason, and whoever restores it should re-read the description and the closing
        date before a stranger spends an evening on a cover letter for it.
        """
        posting = self.get_object()
        if posting.archived_at is None:
            return Response({"detail": "That role is not archived."},
                            status=status.HTTP_400_BAD_REQUEST)
        posting.archived_at = None
        posting.status = "draft"
        posting.save(update_fields=["archived_at", "status", "updated_at"])
        return Response(self.get_serializer(posting).data)


class JobApplicationAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """Candidates. READ-AUDITED — see the module docstring."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("careers.applications.manage")]
    audit_reads = True
    audit_serializers = (JobApplicationWriteSerializer,)
    filter_backends = [DjangoFilterBackend]
    filterset_class = JobApplicationFilter
    http_method_names = ["get", "patch", "delete", "head", "options"]
    queryset = (
        JobApplication.objects.select_related("job", "location", "reviewed_by")
        .order_by("-created_at", "-id")
    )

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return JobApplicationWriteSerializer
        if self.action == "list":
            return JobApplicationListSerializer
        return JobApplicationDetailSerializer

    def perform_update(self, serializer):
        """Stamp the reviewer only when the STATUS moved.

        "Reviewed by" answers "who decided", and fixing a typo in the notes is not a
        decision. Comparing against the pre-save value is the only way to tell — a
        PATCH carrying the status it already had is a no-op, not a review.
        """
        before = serializer.instance.status
        application = serializer.save()
        if application.status != before:
            services.mark_reviewed(application, self.request.user)
            application.save(update_fields=["reviewed_by", "reviewed_at", "updated_at"])

    def destroy(self, request, *args, **kwargs):
        """PERMANENT. The row goes and so does the CV.

        Elevates above the viewset's `careers.applications.manage` floor to
        `careers.applications.delete` (Owner only) — inline, like
        `ProductAdminViewSet.destroy`, so the declared class permission stays the truth
        the surface guard reads. Checked BEFORE the object lookup, so an unauthorised
        caller gets a clean 403 rather than a 404 that tells them whether the id exists.

        FILE FIRST, THEN ROW. If the object delete fails the row survives and the screen
        reports it, which is recoverable. The other order leaves a CV in the bucket that
        nothing references and nobody can find to remove — the exact state a deletion
        request exists to prevent.
        """
        if "careers.applications.delete" not in scopes_for_user(request.user):
            raise exceptions.PermissionDenied(
                "Deleting an application requires the careers.applications.delete scope, "
                "which only the Owner holds."
            )
        application = self.get_object()
        # Snapshot for the audit row BEFORE anything is destroyed. Deliberately NOT the
        # candidate's email, phone or CV: the audit log is read by more people than this
        # screen is, and a deletion must not be the thing that copies personal data into
        # a table nobody thought of as holding it.
        self._deleted = {
            "id": application.pk,
            "job_title": application.job_title,
            "location_label": application.location_label,
            "status": application.status,
            "applied_at": application.created_at.isoformat(),
        }
        if application.resume_key:
            resume_storage.delete(application.resume_key)
        application.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _changes(self, response) -> dict:
        changes = super()._changes(response)
        if self.request.method.upper() == "DELETE" and hasattr(self, "_deleted"):
            changes["deleted"] = self._deleted
        return changes

    @action(detail=True, methods=["get"])
    def resume(self, request, pk=None):
        """One CV, for sixty seconds.

        `?disposition=inline` opens it in a tab (the reviewer reading it), anything else
        downloads it. Both land on the S3 host, never on ours — see the module docstring.

        This route is read-audited by inheritance (`audit_reads` on the class), which is
        the point: it is the single most sensitive read on the admin surface, and the
        audit row is the only thing that can later say who fetched whose CV.
        """
        application = self.get_object()
        if not application.resume_key:
            return Response({"detail": "This application has no CV attached."},
                            status=status.HTTP_404_NOT_FOUND)
        inline = request.query_params.get("disposition") == "inline"
        filename = self._download_name(application)
        url = resume_storage.download_url(
            application.resume_key, filename=filename, inline=inline
        )
        if url is not None:
            return Response({"url": url, "filename": filename})
        # Dev/test: no bucket to presign against, so stream it. Never reached in
        # production — `resume_storage.uses_s3()` is true there.
        handle = default_storage.open(application.resume_key, "rb")
        response = FileResponse(
            handle,
            content_type=application.resume_content_type or "application/octet-stream",
        )
        response["Content-Disposition"] = (
            f"{'inline' if inline else 'attachment'}; {rfc5987_filename(filename)}"
        )
        response["Cache-Control"] = "private, no-store"
        return response

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Counts for the screen's filter chips and the per-role rail.

        AN ACTION ON THIS VIEWSET RATHER THAN A VIEW OF ITS OWN, and that is a decision
        the audit guard made for me. Written separately it declared
        `careers.applications.manage`, which `PII_SCOPE_PREFIXES` matches — so the guard
        demanded `audit_reads` on an endpoint that returns nothing but integers. The
        honest fix was not an exception to the rule but fewer endpoints: folded in here
        it inherits the scope, the auditing and the queryset, and there is one less place
        for the two to drift.
        """
        rows = (
            JobApplication.objects.values("status")
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
            "by_job": list(
                JobPosting.objects.annotate(
                    application_count=Count("applications", distinct=True),
                    new_count=Count(
                        "applications",
                        filter=Q(applications__status="new"),
                        distinct=True,
                    ),
                )
                .filter(application_count__gt=0)
                .values("id", "title", "slug", "application_count", "new_count")
                .order_by("-application_count")
            ),
        })

    @staticmethod
    def _download_name(application: JobApplication) -> str:
        """`Ada Obi - Sales Representative.pdf`.

        Built from the candidate and the role rather than kept as the uploaded name,
        because a folder of twenty files called `CV.pdf` and `resume (1).docx` is what
        the uploaded names actually produce. The extension comes off the STORED key, not
        off the original filename — the key's extension is the one the bytes were sniffed
        against.
        """
        import os

        ext = os.path.splitext(application.resume_key)[1] or ".pdf"
        stem = f"{application.full_name} - {application.job_title}".strip(" -")
        # `/` and `\` would be read as path separators by some clients; the rest of the
        # sanitising (quotes, control characters, non-ASCII) is `rfc5987_filename`'s job.
        stem = stem.replace("/", "-").replace("\\", "-")
        return f"{stem[:120]}{ext}"
