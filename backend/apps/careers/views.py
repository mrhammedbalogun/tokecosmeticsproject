"""The public careers API. Anonymous, and the only surface in this project that takes a
file from somebody with no account.

    GET  /api/v1/careers/jobs/            -> every role on the board
    GET  /api/v1/careers/jobs/<slug>/     -> one role
    POST /api/v1/careers/uploads/         -> a presigned ticket for ONE CV
    POST /api/v1/careers/uploads/direct/  -> DEV ONLY stand-in for S3's POST form
    POST /api/v1/careers/jobs/<slug>/apply/

── WHERE THE ABUSE CONTROLS SIT, AND WHY THERE ────────────────────────────────

Turnstile is verified when the UPLOAD TICKET is minted, not when the application is
submitted. That is the expensive moment — a ticket is a write authorisation into the
bucket that also holds `backups/postgres/` — and it is the one a bot must pay for
before it can do anything at all. Paying it later would mean handing out write tickets
to unauthenticated callers and hoping they come back.

The apply endpoint is then gated by three things that cost a human nothing: a
per-IP throttle, a honeypot field, and the fact that it needs a ticket key it cannot
guess. `CF-Connecting-IP` is what both throttles key on, which is the reason the
storefront posts here DIRECTLY instead of through its Next BFF — see
`apps.accounts.throttling`, whose module docstring measures what a proxy hop does to
this.
"""
import logging

from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.throttling import ScopedRateThrottle
from apps.accounts.turnstile import require_turnstile
from apps.careers import resume_storage, services
from apps.careers.emails import notify_application_received
from apps.careers.serializers import (
    ApplicationCreateSerializer,
    ApplicationResultSerializer,
    JobPostingSerializer,
    UploadTicketRequestSerializer,
)
from apps.cms.s3_uploads import UnsafeKeyError

logger = logging.getLogger(__name__)
_security_logger = logging.getLogger("apps.security")


class JobListView(generics.ListAPIView):
    """The board. Unpaginated on purpose.

    A shop this size advertises a handful of roles at a time, and the page groups and
    filters them in the browser — paginating six cards would add a control that does
    nothing and a second request that returns nothing. If this ever reaches dozens,
    paginate it then; the storefront already handles a `results` envelope elsewhere.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    serializer_class = JobPostingSerializer
    pagination_class = None

    def get_queryset(self):
        return services.public_postings()


class JobDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    serializer_class = JobPostingSerializer
    lookup_field = "slug"

    def get_queryset(self):
        return services.public_postings()


class ResumeUploadTicketView(APIView):
    """Mint one presigned upload, for one key, once.

    THROTTLED HARDER THAN THE APPLY CALL, because this is the endpoint that creates
    objects in the bucket. A wasted ticket leaves an orphan in `incoming/` for the
    lifecycle rule to reclaim; a lot of wasted tickets is a storage bill, so the rate is
    set to the pace of somebody genuinely re-picking a file rather than to the pace of a
    form being filled.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "careers_upload"
    serializer_class = UploadTicketRequestSerializer

    def post(self, request):
        # BEFORE anything is minted. `require_turnstile` is a no-op while the secret is
        # unset (dev), and fails closed on every other path.
        require_turnstile(request)
        serializer = UploadTicketRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ticket = resume_storage.new_ticket(serializer.validated_data["filename"])
        except resume_storage.ResumeRejected as exc:
            return Response({"filename": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        except UnsafeKeyError:
            # The allow-list already ran, so reaching here means the two disagree. That is
            # a bug in our own code, not a bad request; log it and refuse generically.
            logger.exception("careers: refused to mint a key for an allow-listed extension")
            return Response(
                {"detail": "We could not start that upload. Try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ticket, status=status.HTTP_201_CREATED)


class ResumeDirectUploadView(APIView):
    """DEV AND TEST ONLY. Stands in for the S3 POST form when no bucket is configured.

    Registered unconditionally so the URLconf is the same everywhere, and refused by
    `resume_storage.store_direct_upload` the moment a bucket exists — the guard lives in
    the storage module rather than here because this view is the kind of thing a refactor
    moves and a comment does not follow.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "careers_upload"
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        key = request.data.get("key") or ""
        upload = request.FILES.get("file")
        if upload is None:
            return Response({"file": ["Attach your CV."]}, status=status.HTTP_400_BAD_REQUEST)
        try:
            resume_storage.store_direct_upload(key, upload)
        except resume_storage.ResumeRejected as exc:
            return Response({"file": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        except UnsafeKeyError:
            _security_logger.warning("careers: direct upload refused for key %r", key[:120])
            return Response({"detail": "Upload refused."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"key": key}, status=status.HTTP_201_CREATED)


class ApplyView(APIView):
    """Take one application. Always answers the same way when it works.

    See `services` for why there is no "you have already applied" and why the role is
    re-read under a lock.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "careers_apply"
    serializer_class = ApplicationCreateSerializer

    def post(self, request, slug: str):
        job = services.public_postings().filter(slug=slug).first()
        if job is None:
            raise NotFound("We could not find that role.")

        serializer = ApplicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # THE HONEYPOT. `website` is rendered off-screen with `autocomplete="off"` and no
        # label; a human never sees it and a real browser never fills it. Answering 201
        # rather than 400 is the point — a bot that is told it failed retries differently,
        # and one that is told it succeeded stops.
        if (data.get("website") or "").strip():
            _security_logger.info("careers: honeypot tripped on %s", slug)
            return Response({"job_title": job.title}, status=status.HTTP_201_CREATED)

        try:
            application = services.record_application(
                job=job,
                full_name=data["full_name"],
                email=data["email"],
                phone=data["phone"],
                cover_letter=data.get("cover_letter", ""),
                location_id=data.get("location"),
                incoming_key=data["upload_key"],
                resume_filename=data["resume_filename"],
            )
        except services.ApplicationRefused as exc:
            body = {exc.field: [exc.message]} if exc.field else {"detail": exc.message}
            return Response(body, status=exc.status)
        except resume_storage.ResumeRejected as exc:
            return Response({"resume": [str(exc)]}, status=status.HTTP_400_BAD_REQUEST)
        except UnsafeKeyError:
            # A key outside the quarantine prefix reached us. Nothing a real form can
            # produce; logged as a security event and refused without explaining why.
            _security_logger.warning(
                "careers: apply refused an out-of-prefix key for %s", slug
            )
            return Response(
                {"detail": "We could not read that upload. Attach your CV again."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # AFTER COMMIT. Production sets `ATOMIC_REQUESTS = True` (config/settings/prod.py),
        # so the whole request is one transaction and this really does defer: mail sent
        # inside it would be mail sent for an application that can still roll back.
        #
        # In dev and tests there is no outer transaction — `record_application`'s own has
        # already committed by the time we get here — so `on_commit` runs INLINE. That is
        # the autocommit trap this project has been bitten by before, and here it is
        # harmless in both directions: inline or deferred, the row exists, and
        # `notify_application_received` only enqueues.
        transaction.on_commit(lambda: notify_application_received(application.pk))

        return Response(
            ApplicationResultSerializer(application).data, status=status.HTTP_201_CREATED
        )
