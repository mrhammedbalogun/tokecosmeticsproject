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

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.notifications.admin_serializers import (
    NotificationRecipientSerializer,
    event_catalog,
)
from apps.notifications.models import NotificationRecipient
from apps.notifications.recipient_admin import RecipientAdminMixin

# Re-exported: `ResendConfirmationThrottle` moved to `recipient_admin` with the action
# that uses it, and this name is imported by tests and by settings' rate comment.
from apps.notifications.recipient_admin import ResendConfirmationThrottle  # noqa: F401


class NotificationRecipientAdminViewSet(
    # ORDER MATTERS, AND NOT IN THE USUAL DIRECTION. `AdminAuditMixin`'s own docstring
    # says to apply it first so its `dispatch` wraps the view's — and it still does,
    # because `RecipientAdminMixin` defines no `dispatch` at all. What `RecipientAdminMixin`
    # DOES define is `resolve_allowlist`, and with the audit mixin first that override was
    # shadowed: the per-action allowlist stopped running and `test-send` went back to
    # logging an address from the request body, which is the exact bug its docstring
    # describes. Caught by `test_a_test_send_never_logs_an_address_from_the_request`.
    # This order also makes the `super().resolve_allowlist()` call inside the mixin reach
    # the audit mixin's default, which is what it is written to expect.
    RecipientAdminMixin, AdminAuditMixin, viewsets.ModelViewSet
):
    """`/admin/notification-recipients/` — the subscriber list, all events at once.

    NOT PAGINATED and not filtered by event. The whole point of the screen is to answer
    "who hears about what" in one glance, and a handful of events with a handful of
    addresses each is a page, not a dataset. Paginating it would let a recipient hide on
    page two of a list whose entire job is to have nothing hidden in it.

    THE ACTIONS LIVE IN `RecipientAdminMixin`, shared with the careers notifications
    surface. They were extracted rather than copied when that second surface arrived; the
    move also fixed a latent bug here, which the mixin's docstring records: each action
    used to look its row up through `NotificationRecipient.objects` rather than through
    `get_queryset()`. Harmless on this viewset, whose queryset is every row — and a
    privilege escalation the moment a narrower one exists over the same table.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("settings.manage")]
    serializer_class = NotificationRecipientSerializer
    audit_serializers = (NotificationRecipientSerializer,)
    queryset = NotificationRecipient.objects.select_related("user").all()
    pagination_class = None
    http_method_names = ["get", "post", "delete", "head", "options"]

    @action(detail=False, methods=["get"])
    def events(self, request):
        """`GET …/events/` — the registry the screen renders its sections from.

        An endpoint rather than a constant copied into the frontend, unlike
        `admin/src/lib/staff.ts`'s `ROLES`. The reasoning there was that the role list
        changes only with an RBAC redesign; this list is meant to grow, and the whole
        promise of the registry is that adding an event needs no frontend change. A copy
        in TypeScript would break that promise on the first new event.

        NOT on the shared mixin: a single-event screen has no use for the whole catalogue,
        and handing it one would be scope creep in the literal sense.
        """
        return Response(event_catalog())
