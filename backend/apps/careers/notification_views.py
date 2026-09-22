"""Who gets emailed when somebody applies — the Careers screen's Notifications tab.

The same table, the same confirmation flow and the same actions as the Owner-only
Email Notifications screen (`apps/notifications/`), narrowed to exactly one event so the
people who do the hiring can fix their own alerts without holding `settings.manage`.

── THE EVENT IS PINNED IN THREE PLACES, AND ALL THREE ARE LOAD-BEARING ─────────────

`order.paid` has nine real recipients on production today, several of them bare external
addresses. A holder of `careers.notifications.manage` must not be able to read, create,
delete or confirm any of them. So:

1. **`get_queryset()`** filters to the one event, and every route resolves through it —
   list, detail, destroy, and the body-addressed `@action`s via the mixin's
   `_row_or_none`. That last part is why the actions were extracted into
   `RecipientAdminMixin` rather than copied: the originals looked their row up through
   the bare manager, which is fine on an unfiltered viewset and an escalation here.
2. **The serializer forces `event`** rather than validating it. A client-supplied value
   is ignored outright, so there is no code path where the event comes from the request.
3. **`mark_confirmed` is refused entirely** unless the caller ALSO holds `settings.manage`
   — see `mark_confirmed` below for why that one action escapes the other two guards.

A row outside the queryset answers 404 and not 403, so the endpoint cannot be used to
discover which recipient ids belong to other events.

── WHAT THIS GRANT STILL ALLOWS, STATED PLAINLY ────────────────────────────────────

A Manager can point the careers alert at any address they can type. The alert carries a
candidate's NAME and the role they applied for — so this is the power to tell an outside
address that a named person is job-hunting. It is bounded (no contact details, no CV, no
cover letter — `apps/careers/tests/test_emails.py` pins that), every add is audited with
the actor's email, and an external address receives nothing until it confirms. It is not
nothing, and `rbac.py` records the decision rather than leaving it implied.
"""
from __future__ import annotations

from rest_framework import exceptions, viewsets

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope, scopes_for_user
from apps.careers.emails import EVENT_APPLICATION_RECEIVED
from apps.careers.notification_serializers import CareersRecipientSerializer
from apps.core.audit import AdminAuditMixin
from apps.notifications.models import NotificationRecipient
from apps.notifications.recipient_admin import RecipientAdminMixin


class CareersNotificationAdminViewSet(
    # See `NotificationRecipientAdminViewSet` for why the recipient mixin goes FIRST.
    RecipientAdminMixin, AdminAuditMixin, viewsets.ModelViewSet
):
    """`/admin/careers/notifications/` — the careers alert's subscriber list."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("careers.notifications.manage")]
    serializer_class = CareersRecipientSerializer
    audit_serializers = (CareersRecipientSerializer,)
    pagination_class = None
    http_method_names = ["get", "post", "delete", "head", "options"]

    # NOT `audit_reads`. This table holds staff and shop addresses, never a candidate's:
    # the applications surface is where the personal data is, and it carries the
    # `careers.applications.` scope prefix that forces read-auditing. Auditing a read of
    # "who do we email" would add a row every time the tab is opened and train whoever
    # reads the log to skim it.

    def get_queryset(self):
        """THE FENCE. One event, on every route, including the detail ones."""
        return (
            NotificationRecipient.objects.select_related("user")
            .filter(event=EVENT_APPLICATION_RECEIVED)
            .order_by("email", "user_id")
        )

    def check_may_vouch(self, request) -> None:
        """Vouching for an address is OWNER-ONLY even here. Inline elevation, like
        `ProductAdminViewSet.destroy`, so the declared class permission stays the truth
        the surface guard reads.

        WHY THIS ONE ACTION ESCAPES THE EVENT FENCE. `notifications.confirm.confirm()`
        marks every pending row for the SAME ADDRESS, filtered on the email alone and not
        on the event — deliberately, because confirmation is a property of an address
        rather than of one subscription. Correct as a consent model, and it means a
        careers-scoped caller who vouched for an address would also activate that
        address's pending `order.paid` row, which is precisely the Owner-only act
        `apps/notifications/admin_views.py` reserves. The queryset fence cannot stop it,
        because the reach happens inside `confirm()` after the row has been found.

        So the cheap, honest fix is to keep the act where it already lived. A Manager can
        still add, remove, resend and test; what they cannot do is substitute their word
        for an address's own click.

        The indirect path stays open and is fine: a Manager adds an address, the address
        is emailed a link, and the PERSON THERE clicks it — which confirms their other
        pending rows too. That is the designed meaning of per-address consent, and it
        needs the address holder to act.

        A HOOK rather than an override of `mark_confirmed` itself: overriding the
        decorated action loses the `@action` metadata the router reads off it, and the
        route 405s. Found the hard way.
        """
        if "settings.manage" not in scopes_for_user(request.user):
            raise exceptions.PermissionDenied(
                "Only the Owner can confirm an address without its own click. Use "
                "Resend confirmation and ask them to click the link."
            )
