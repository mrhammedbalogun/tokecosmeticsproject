"""The recipient-management actions, extracted so two surfaces can share ONE copy.

WHY THIS FILE EXISTS. `/admin/notification-recipients/` (Owner-only, every event) and
`/admin/careers/notifications/` (Owner + Manager, one event) do the same five things to
the same table. Written twice they would drift, and the half that drifted would be the
half a reviewer did not read — so the behaviour lives here and the two viewsets differ
only in their QUERYSET and their SCOPE.

── THE LOOKUP RULE, WHICH IS THE WHOLE SECURITY PROPERTY ───────────────────────────

Every action below finds its row through `self.get_queryset()` and never through
`NotificationRecipient.objects`. That distinction is load-bearing and it was a latent
bug before this refactor: the original actions each did
`NotificationRecipient.objects.filter(pk=body["recipient_id"])`, which is fine on a
viewset whose queryset is unfiltered and is a PRIVILEGE ESCALATION on one whose queryset
is scoped to a single event. Without this rule a Manager holding
`careers.notifications.manage` could pass the id of one of the nine real `order.paid`
recipients and mark it confirmed, or fire a test send at it.

A row outside the queryset answers 404, not 403 — the same answer as a row that does not
exist, so the endpoint cannot be used to discover which ids belong to other events.
"""
from __future__ import annotations

from functools import partial

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.notifications.admin_serializers import StaffPickerSerializer, TestSendSerializer
from apps.notifications.confirm import (
    confirm as confirm_address,
    inherit_confirmation,
    send_confirmation,
)
from apps.notifications.events import EVENTS_BY_CODE
from apps.notifications.preview import preview_context
from apps.notifications.tasks import send_email_task

User = get_user_model()


class ResendConfirmationThrottle(ScopedRateThrottle):
    """Caps how often a confirmation can be re-sent. See the rate's comment in settings.

    Scoped rather than keyed on the recipient row: the thing worth limiting is how much
    outbound mail one staff session can generate, and a per-row key would let a caller
    rotate through rows to send an unbounded total.
    """

    scope = "recipient_confirm_resend"


class RecipientAdminMixin:
    """The five actions, parameterised only by `get_queryset()`.

    Mix in BEFORE the viewset base (`class X(AdminAuditMixin, RecipientAdminMixin,
    ModelViewSet)`) so the `@action` routes are discovered by the router.
    """

    def _row_or_none(self, request):
        """Resolve `recipient_id` from the body, WITHIN this viewset's queryset.

        Returns `(row, error_response)`; exactly one is None. See the module docstring
        for why the queryset and not the manager.
        """
        body = TestSendSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        row = (
            self.get_queryset()
            .select_related("user")
            .filter(pk=body.validated_data["recipient_id"])
            .first()
        )
        if row is None:
            return None, Response(
                {"detail": "That recipient no longer exists."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return row, None

    def perform_create(self, serializer):
        """Create the row, then mail an external address its confirmation link.

        ON COMMIT, for the reason the test-send action gives: `AdminAuditMixin` wraps this
        request in a transaction, and a confirmation mailed for a row that then rolls back
        is a link pointing at nothing. Staff rows are confirmed by construction and are
        sent nothing — see `models.py`.
        """
        recipient = serializer.save()
        if recipient.user_id is None and not inherit_confirmation(recipient):
            transaction.on_commit(partial(send_confirmation, recipient))

    def resolve_allowlist(self) -> tuple[str, ...]:
        """Per-ACTION allowlist, because these viewsets' POST routes take two different
        bodies.

        THE BUG THIS FIXES WAS FOUND BY READING THE AUDIT TABLE. The default allowlist is
        built from `serializer_class` — `event`, `user`, `email` — and `changes` is built
        from `request.data`, so a `test-send` call carrying a junk `email` key logged it:

            test_send  changes={'email': 'attacker@evil.test'}

        …for a send that went to the STORED address and never looked at that key. An
        audit row naming a value the action ignored is worse than no row at all: it is
        evidence pointing at something that did not happen, in the one table that exists
        to be believed. `recipient_id` is the entire content of this decision, and the
        address behind it is in that recipient's own `create` row.
        """
        if getattr(self, "action", None) in ("test_send", "mark_confirmed"):
            return ("recipient_id",)
        return super().resolve_allowlist()

    @action(detail=False, methods=["get"], url_path="staff-options")
    def staff_options(self, request):
        """The account picker. Active staff only — offering a deactivated colleague would
        create a row that resolves to nobody the moment it is saved."""
        people = User.objects.filter(is_active=True, is_staff=True).order_by("email")
        return Response(StaffPickerSerializer(people, many=True).data)

    @action(detail=False, methods=["post"], url_path="resend-confirmation",
            throttle_classes=[ResendConfirmationThrottle])
    def resend_confirmation(self, request):
        """`POST …/resend-confirmation/` {"recipient_id": n} — mint a fresh link.

        THE RECOVERY PATH for the two ways confirmation stalls: the link expired (7 days)
        or the mail never arrived. Both leave a row visibly pending on the screen with
        this button next to it, which is the whole reason a short TTL is safe to choose.

        Refuses an already-confirmed row rather than quietly re-sending: a second
        confirmation email to someone already receiving alerts reads as a security
        incident to the person getting it.
        """
        row, error = self._row_or_none(request)
        if error is not None:
            return error
        if row.user_id is not None:
            return Response(
                {"detail": "Staff accounts do not need to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if row.confirmed_at is not None:
            return Response({"detail": "That address is already confirmed."},
                            status=status.HTTP_400_BAD_REQUEST)

        transaction.on_commit(partial(send_confirmation, row))
        return Response({"sent_to": row.email})

    @action(detail=False, methods=["post"], url_path="mark-confirmed")
    def mark_confirmed(self, request):
        """`POST …/mark-confirmed/` {"recipient_id": n} — vouch for an address instead of
        waiting for its click.

        WHAT IS TRADED AWAY, DELIBERATELY. The click proves two things nothing else can:
        the address is deliverable, and a human there agreed. This override discards both
        and substitutes the caller's word — which is acceptable exactly because the act is
        scoped and audited, so "who vouched, for what, when" is on the record where the
        address's own consent would have been. It exists for the address the shop
        personally controls, where the email round-trip is ceremony.

        GOES THROUGH `confirm()`, THE SAME DOOR THE CLICK USES. Confirmation is a
        property of the ADDRESS, not the row, and an override that only touched one row
        would quietly create a second, weaker kind of confirmed — every other pending row
        for the address still dark, `inherit_confirmation` not firing for later adds.
        One path means one meaning.

        THAT CROSS-ROW REACH IS WHY THIS ACTION IS THE ONE TO WATCH on a scoped viewset.
        `confirm()` marks every pending row for the SAME ADDRESS, including rows for
        events this viewset cannot see. That is correct — the address really has proved
        itself once and for all — but it means a careers-scoped caller can confirm an
        `order.paid` row for an address that is already pending there. It is bounded:
        they must first add that exact address to the careers list themselves, which is
        an audited act naming them, and they never learn whether the other row existed.
        Recorded here rather than discovered later.

        No throttle: unlike resend-confirmation this sends no mail, so there is nothing
        for a caller to amplify.
        """
        # A HOOK, not an overridable action. A subclass that simply overrode
        # `mark_confirmed` would lose the `@action` metadata the router reads off the
        # decorated function and the route would 405 — which is how the careers viewset
        # first failed. Subclasses narrow the permission here instead.
        self.check_may_vouch(request)

        row, error = self._row_or_none(request)
        if error is not None:
            return error
        if row.user_id is not None:
            return Response(
                {"detail": "Staff accounts do not need to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if row.confirmed_at is not None:
            return Response({"detail": "That address is already confirmed."},
                            status=status.HTTP_400_BAD_REQUEST)

        confirm_address(row)
        return Response({"confirmed": row.email})

    def check_may_vouch(self, request) -> None:
        """Raise `PermissionDenied` if this caller may not vouch for an address.

        Open by default: on the Owner-only viewset the class permission has already
        answered this. A viewset whose scope is WIDER than `settings.manage` must narrow
        it here, because `confirm()` reaches every pending row for the address regardless
        of event — see `apps/careers/notification_views.py`.
        """
        return None

    @action(detail=False, methods=["post"], url_path="test-send")
    def test_send(self, request):
        """`POST …/test-send/` {"recipient_id": n} — send this row a sample of its event.

        THIS EXISTS BECAUSE NO SCOPE PROTECTS AGAINST A TYPO. A scope keeps strangers off
        the list; it does nothing about `careers@gmali.com`, which would silently receive
        every application forever and never be noticed, because the symptom of a wrong
        address is exactly the symptom of a working one — nothing.

        THE ADDRESS IS TAKEN FROM THE STORED ROW, NEVER FROM THE REQUEST. An endpoint that
        mails an address in the body is an open relay wearing a staff login: it would send
        our branded, authenticated mail to anywhere a caller named, without leaving a
        recipient row behind to show for it. Requiring the row to exist first means a test
        send can only ever go somewhere the audit log already records a decision about.

        Sent through Celery like every other mail, so a Resend outage is a retry rather
        than a 502 on a settings screen.
        """
        row, error = self._row_or_none(request)
        if error is not None:
            return error

        # AN UNCONFIRMED ADDRESS GETS NOTHING BUT ITS CONFIRMATION LINK. Allowing a test
        # send here would put event-shaped content in an unconfirmed inbox, which is the
        # exact delivery the confirmation gate exists to withhold — and it would let the
        # caller satisfy themselves that a mistyped address "works" without the address
        # ever having agreed. The confirmation email is the deliverability proof; the
        # screen offers Resend confirmation in this button's place.
        if not row.is_confirmed:
            return Response(
                {"detail": "That address has not confirmed yet. Resend its confirmation "
                           "link instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        address = row.address
        if not address:
            # A staff row whose account is deactivated. Saying so is more useful than
            # sending nothing and reporting success.
            return Response(
                {"detail": "That staff account is no longer active, so it receives no mail."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        event = EVENTS_BY_CODE.get(row.event)
        if event is None:
            return Response({"detail": f"{row.event} is no longer a notification event."},
                            status=status.HTTP_400_BAD_REQUEST)

        # ENQUEUED ON COMMIT, not inline. `AdminAuditMixin.dispatch` wraps this
        # request in a transaction and writes the audit row inside it, so a failure
        # there rolls the request back — and a test email that has already left is one
        # the log has no record of anybody asking for. `on_commit` keeps the two facts
        # in step, which is the same rule the order emails follow.
        transaction.on_commit(
            partial(
                send_email_task.delay,
                event.template,
                address,
                preview_context(row.event),
            )
        )
        return Response({"sent_to": address})
