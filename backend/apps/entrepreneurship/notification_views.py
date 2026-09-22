"""Who gets emailed when a student applies — the programme screen's Notifications tab.

The same table, the same confirmation flow and the same actions as the Owner-only Email
Notifications screen (`apps/notifications/`), narrowed to exactly one event so whoever
runs the programme can fix their own alerts without holding `settings.manage`.

── THE EVENT IS PINNED IN THREE PLACES, AND ALL THREE ARE LOAD-BEARING ─────────────

`order.paid` has nine real recipients on production today, several of them bare external
addresses. A holder of `entrepreneurship.notifications.manage` must not be able to read,
create, delete or confirm any of them. So:

1. **`get_queryset()`** filters to the one event, and every route resolves through it —
   list, detail, destroy, and the body-addressed `@action`s via the mixin's
   `_row_or_none`.
2. **The serializer forces `event`** rather than validating it, so there is no code path
   where the event comes from the request.
3. **`mark_confirmed` is refused entirely** unless the caller ALSO holds
   `settings.manage` — see `check_may_vouch` below for why that one action escapes the
   other two guards.

A row outside the queryset answers 404 and not 403, so the endpoint cannot be used to
discover which recipient ids belong to other events.

── WHAT THIS GRANT STILL ALLOWS, STATED PLAINLY ────────────────────────────────────

A Manager can point the programme alert at any address they can type. The alert carries
a student's NAME and where they study — so this is the power to tell an outside address
that a named young person is asking for a business opportunity. It is bounded (no email,
no phone, no motivation letter — `apps/entrepreneurship/tests/test_emails.py` pins
that), every add is audited with the actor's email, and an external address receives
nothing until it confirms. It is not nothing, and `rbac.py` records the decision rather
than leaving it implied.
"""
from __future__ import annotations

from rest_framework import exceptions, viewsets

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope, scopes_for_user
from apps.core.audit import AdminAuditMixin
from apps.entrepreneurship.emails import EVENT_APPLICATION_RECEIVED
from apps.entrepreneurship.notification_serializers import ProgrammeRecipientSerializer
from apps.notifications.models import NotificationRecipient
from apps.notifications.recipient_admin import RecipientAdminMixin


class ProgrammeNotificationAdminViewSet(
    # See `NotificationRecipientAdminViewSet` for why the recipient mixin goes FIRST:
    # `AdminAuditMixin` after it, or its `resolve_allowlist` shadows the per-action one
    # and test-send starts logging addresses from the request body again.
    RecipientAdminMixin, AdminAuditMixin, viewsets.ModelViewSet
):
    """`/admin/entrepreneurship/notifications/` — the programme alert's subscribers."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("entrepreneurship.notifications.manage")]
    serializer_class = ProgrammeRecipientSerializer
    audit_serializers = (ProgrammeRecipientSerializer,)
    pagination_class = None
    http_method_names = ["get", "post", "delete", "head", "options"]

    # NOT `audit_reads`. This table holds staff and shop addresses, never a student's:
    # the applications surface is where the personal data is, and it carries the
    # `entrepreneurship.applications.` scope prefix that forces read-auditing. Auditing
    # a read of "who do we email" would add a row every time the tab is opened and train
    # whoever reads the log to skim it.

    def get_queryset(self):
        """THE FENCE. One event, on every route, including the detail ones."""
        return (
            NotificationRecipient.objects.select_related("user")
            .filter(event=EVENT_APPLICATION_RECEIVED)
            .order_by("email", "user_id")
        )

    def check_may_vouch(self, request) -> None:
        """Vouching for an address is OWNER-ONLY even here. Inline elevation, so the
        declared class permission stays the truth the surface guard reads.

        WHY THIS ONE ACTION ESCAPES THE EVENT FENCE. `notifications.confirm.confirm()`
        marks every pending row for the SAME ADDRESS, filtered on the email alone and not
        on the event — deliberately, because confirmation is a property of an address
        rather than of one subscription. Correct as a consent model, and it means a
        programme-scoped caller who vouched for an address would also activate that
        address's pending `order.paid` row. The queryset fence cannot stop it, because
        the reach happens inside `confirm()` after the row has been found.

        A Manager can still add, remove, resend and test; what they cannot do is
        substitute their word for an address's own click.

        A HOOK rather than an override of `mark_confirmed` itself: overriding the
        decorated action loses the `@action` metadata the router reads off it, and the
        route 405s. The careers board found that the hard way.
        """
        if "settings.manage" not in scopes_for_user(request.user):
            raise exceptions.PermissionDenied(
                "Only the Owner can confirm an address without its own click. Use "
                "Resend confirmation and ask them to click the link."
            )
