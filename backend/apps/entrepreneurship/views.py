"""The public programme API. Anonymous.

    GET  /api/v1/entrepreneurship/config/  -> is the intake open, and which countries
    POST /api/v1/entrepreneurship/apply/

── WHERE THE ABUSE CONTROLS SIT, AND WHY THEY DIFFER FROM CAREERS ──────────────

The careers form verifies Turnstile when it mints an S3 UPLOAD TICKET, because that is
the expensive moment: a ticket is a write authorisation into a bucket. **This form
carries no file at all**, so there is no ticket, no quarantine prefix and no byte
sniffing — and therefore no earlier moment to put the check at. Turnstile is verified on
the apply call itself, which is the only call there is.

The rest is the same three cheap gates careers uses: a per-IP throttle, a honeypot
field, and a submission that writes one small row. `CF-Connecting-IP` is what the
throttle keys on, which is the reason the storefront posts here DIRECTLY instead of
through its Next BFF — see `apps.accounts.throttling`, whose module docstring measures
what a proxy hop does to this.

── THE CONFIG READ IS NOT THE AUTHORITY ────────────────────────────────────────

`config/` exists so the page can render "applications are closed" instead of a form that
will be refused. It is cached by the storefront for minutes at a time and is therefore
stale by construction. `services.record_application` re-reads the same row under a lock
on every submit, and that read is the one that decides.
"""
import logging

from django.db import transaction
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.throttling import ScopedRateThrottle
from apps.accounts.turnstile import require_turnstile
from apps.entrepreneurship import services
from apps.entrepreneurship.emails import notify_application_received
from apps.entrepreneurship.serializers import (
    ApplicationCreateSerializer,
    ApplicationResultSerializer,
    ProgramConfigSerializer,
)

_security_logger = logging.getLogger("apps.security")


class ProgramConfigView(APIView):
    """Whether the intake is open, and the markets the form offers.

    UNTHROTTLED and cacheable: it is two booleans and a handful of country names, it
    names nobody, and it is read once per page render. Putting a rate on it would only
    ever fire on a CDN revalidation storm, which is not abuse.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    serializer_class = ProgramConfigSerializer

    def get(self, request):
        return Response(ProgramConfigSerializer(ProgramConfigSerializer.build()).data)


class ApplyView(APIView):
    """Take one application. Always answers the same way when it works.

    See `services` for why there is no "you have already applied" and why the intake is
    re-read under a lock.
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "programme_apply"
    serializer_class = ApplicationCreateSerializer

    def post(self, request):
        # BEFORE the row is written and before the serializer runs, so a bot pays the
        # check rather than the database. `require_turnstile` is a no-op while the secret
        # is unset (dev), and fails closed on every other path.
        require_turnstile(request)

        serializer = ApplicationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # THE HONEYPOT. `website` is rendered off-screen with `autocomplete="off"` and no
        # label; a human never sees it and a real browser never fills it. Answering 201
        # rather than 400 is the point — a bot that is told it failed retries
        # differently, and one that is told it succeeded stops.
        if (data.get("website") or "").strip():
            _security_logger.info("entrepreneurship: honeypot tripped")
            return Response({"full_name": data["full_name"]},
                            status=status.HTTP_201_CREATED)

        try:
            application = services.record_application(
                country=data["country"],
                full_name=data["full_name"],
                email=data["email"],
                phone=data["phone"],
                institution=data["institution"],
                academic_level=data["academic_level"],
                course_of_study=data["course_of_study"],
                social_handle=data.get("social_handle", ""),
                motivation=data.get("motivation", ""),
            )
        except services.ApplicationRefused as exc:
            body = {exc.field: [exc.message]} if exc.field else {"detail": exc.message}
            return Response(body, status=exc.status)

        # AFTER COMMIT. Production sets `ATOMIC_REQUESTS = True`
        # (config/settings/prod.py), so the whole request is one transaction and this
        # really does defer: mail sent inside it would be mail sent for an application
        # that can still roll back.
        #
        # In dev and tests there is no outer transaction — `record_application`'s own has
        # already committed by the time we get here — so `on_commit` runs INLINE. That is
        # the autocommit trap this project has been bitten by before, and here it is
        # harmless in both directions: inline or deferred, the row exists, and
        # `notify_application_received` only enqueues.
        transaction.on_commit(lambda: notify_application_received(application.pk))

        return Response(
            ApplicationResultSerializer(application).data,
            status=status.HTTP_201_CREATED,
        )
