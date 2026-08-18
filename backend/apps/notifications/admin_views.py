"""The Email Notifications screen's API. Owner-only, audited.

WHY `settings.manage` AND NOT A SCOPE OF ITS OWN, or a softer one. `rbac.py` reserves
Owner-only for "the two surfaces that can escalate privilege or redirect money". This is
the third: a standalone recipient row is an address with no account, no invite and no
second factor that receives order contents forever, and adding one is a single POST. That
is a data-exfiltration channel with the ergonomics of a settings toggle, so it sits beside
the payout bank account rather than beside the delivery prices.

The argument for letting a Manager add THEMSELVES was considered and refused: the endpoint
cannot tell "add me" from "add anyone" without a second permission rule that exists
nowhere else in this codebase, and a six-person shop's Owner adding a colleague is not a
bottleneck worth inventing one for.

NO UPDATE. `http_method_names` omits put and patch. Editing a row in place would let one
audit entry stand for "this used to point at the warehouse and now points at my personal
address"; delete-then-add leaves two entries that each say what happened. The screen is
built the same way, so nothing is lost.
"""
from __future__ import annotations

from functools import partial

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.notifications.admin_serializers import (
    NotificationRecipientSerializer,
    StaffPickerSerializer,
    TestSendSerializer,
    event_catalog,
)
from apps.notifications.confirm import (
    confirm as confirm_address,
    inherit_confirmation,
    send_confirmation,
)
from apps.notifications.events import EVENTS_BY_CODE
from apps.notifications.models import NotificationRecipient
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


class NotificationRecipientAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """`/admin/notification-recipients/` — the subscriber list, all events at once.

    NOT PAGINATED and not filtered by event. The whole point of the screen is to answer
    "who hears about what" in one glance, and four events with a handful of addresses
    each is a page, not a dataset. Paginating it would let a recipient hide on page two of
    a list whose entire job is to have nothing hidden in it.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = NotificationRecipientSerializer
    audit_serializers = (NotificationRecipientSerializer,)
    queryset = NotificationRecipient.objects.select_related("user").all()
    pagination_class = None
    http_method_names = ["get", "post", "delete", "head", "options"]

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
        """Per-ACTION allowlist, because this viewset's two POST routes take two
        different bodies.

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

    @action(detail=False, methods=["get"])
    def events(self, request):
        """`GET …/events/` — the registry the screen renders its sections from.

        An endpoint rather than a constant copied into the frontend, unlike
        `admin/src/lib/staff.ts`'s `ROLES`. The reasoning there was that the role list
        changes only with an RBAC redesign; this list is meant to grow, and the whole
        promise of the registry is that adding an event needs no frontend change. A copy
        in TypeScript would break that promise on the first new event.
        """
        return Response(event_catalog())

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
        body = TestSendSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        row = NotificationRecipient.objects.filter(
            pk=body.validated_data["recipient_id"]
        ).first()
        if row is None:
            return Response({"detail": "That recipient no longer exists."},
                            status=status.HTTP_404_NOT_FOUND)
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
        """`POST …/mark-confirmed/` {"recipient_id": n} — the Owner vouches for an
        address instead of waiting for its click.

        WHAT IS TRADED AWAY, DELIBERATELY. The click proves two things nothing else can:
        the address is deliverable, and a human there agreed. This override discards both
        and substitutes the Owner's word — which is acceptable exactly because the act is
        Owner-only and audited, so "who vouched, for what, when" is on the record where
        the address's own consent would have been. It exists for the address the Owner
        personally controls, where the email round-trip is ceremony.

        GOES THROUGH `confirm()`, THE SAME DOOR THE CLICK USES. Confirmation is a
        property of the ADDRESS, not the row, and an override that only touched one row
        would quietly create a second, weaker kind of confirmed — every other pending row
        for the address still dark, `inherit_confirmation` not firing for later adds.
        One path means one meaning.

        No throttle: unlike resend-confirmation this sends no mail, so there is nothing
        for a caller to amplify.
        """
        body = TestSendSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        row = NotificationRecipient.objects.filter(
            pk=body.validated_data["recipient_id"]
        ).first()
        if row is None:
            return Response({"detail": "That recipient no longer exists."},
                            status=status.HTTP_404_NOT_FOUND)
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

    @action(detail=False, methods=["post"], url_path="test-send")
    def test_send(self, request):
        """`POST …/test-send/` {"recipient_id": n} — send this row a sample of its event.

        THIS EXISTS BECAUSE NO SCOPE PROTECTS AGAINST A TYPO. Owner-only keeps strangers
        off the list; it does nothing about `orders@gmali.com`, which would silently
        receive every order in the shop forever and never be noticed, because the symptom
        of a wrong address is exactly the symptom of a working one — nothing.

        THE ADDRESS IS TAKEN FROM THE STORED ROW, NEVER FROM THE REQUEST. An endpoint that
        mails an address in the body is an open relay wearing a staff login: it would send
        our branded, authenticated mail to anywhere a caller named, without leaving a
        recipient row behind to show for it. Requiring the row to exist first means a test
        send can only ever go somewhere the audit log already records a decision about.

        Sent through Celery like every other mail, so a Resend outage is a retry rather
        than a 502 on a settings screen.
        """
        body = TestSendSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        row = NotificationRecipient.objects.select_related("user").filter(
            pk=body.validated_data["recipient_id"]
        ).first()
        if row is None:
            return Response({"detail": "That recipient no longer exists."},
                            status=status.HTTP_404_NOT_FOUND)

        # AN UNCONFIRMED ADDRESS GETS NOTHING BUT ITS CONFIRMATION LINK. Allowing a test
        # send here would put order-shaped content in an unconfirmed inbox, which is the
        # exact delivery the confirmation gate exists to withhold — and it would let the
        # Owner satisfy themselves that a mistyped address "works" without the address
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
