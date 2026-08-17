"""The one public page in this app: an external recipient confirming their address.

PUBLIC BY NECESSITY. The person clicking has no admin account and never will — that is
the definition of an external recipient. The token in the URL is the entire credential,
which is the same arrangement `apps/orders/tokens.py` uses for order tracking.

MOUNTED OUTSIDE `/api/v1/admin/`, deliberately. Everything under that prefix is walked by
`apps/accounts/tests/test_admin_surface_guard.py`, which requires admin authentication on
each route and keeps a short, argued allowlist for the deliberate exceptions. This route
is not an admin route at all — no staff member ever loads it — so it belongs outside the
prefix rather than inside it with a waiver.

GET SHOWS, POST DOES. See the template for why: mail-security scanners fetch every link
in an incoming message, so a confirm-on-GET endpoint gets auto-clicked by a robot for
precisely the recipients whose employer runs link scanning.
"""
from __future__ import annotations

import logging

from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.notifications.confirm import confirm
from apps.notifications.models import NotificationRecipient
from apps.notifications.tokens import ConfirmTokenError, read_confirm_token

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name="dispatch")
class RecipientConfirmView(View):
    """`/api/v1/notifications/confirm/?token=…`

    CSRF-EXEMPT, and that is not a shortcut. CSRF protects a session-authenticated user
    from having their privileges used by another site; there is no session here and no
    privilege to borrow. The signed token is the only credential, an attacker who has one
    can simply open the link themselves, and forging a confirmation for an address you do
    not control gains you nothing — it subscribes someone else's inbox to a shop's alerts,
    which is a favour to nobody. Requiring a CSRF cookie would instead break the flow for
    anyone whose mail client opens links in a fresh, cookieless context, which is most of
    them.
    """

    template_name = "notifications/confirm.html"

    def get(self, request):
        recipient, error = self._resolve(request)
        if error:
            return self._page(request, **error, status=400)
        return self._page(
            request,
            title="Confirm this address",
            message=(
                f"Press the button to start receiving order notifications from Toke "
                f"Cosmetics at {recipient.email}."
                if not recipient.confirmed_at
                else f"{recipient.email} is already confirmed. Nothing more to do."
            ),
            can_confirm=recipient.confirmed_at is None,
            button_label="Yes, send me these",
        )

    def post(self, request):
        recipient, error = self._resolve(request)
        if error:
            return self._page(request, **error, status=400)

        changed = confirm(recipient)
        logger.info("recipient %s: confirmed %d row(s) for %s",
                    recipient.pk, changed, recipient.email)
        return self._page(
            request,
            title="You're confirmed",
            message=(
                f"{recipient.email} will now receive notifications from Toke Cosmetics. "
                f"To stop them, ask whoever added you to remove the address."
            ),
            can_confirm=False,
        )

    # -- helpers ------------------------------------------------------------------

    def _resolve(self, request):
        """`(recipient, None)` or `(None, page-kwargs describing the refusal)`."""
        try:
            recipient_id, email = read_confirm_token(request.GET.get("token", ""))
        except ConfirmTokenError as exc:
            logger.info("rejected confirmation token: %s", exc)
            return None, {
                "title": "This link has expired",
                "message": (
                    "Confirmation links are valid for 7 days. Ask whoever added your "
                    "address to send a new one."
                ),
            }

        recipient = NotificationRecipient.objects.filter(pk=recipient_id).first()
        # THE ADDRESS IS CHECKED AS WELL AS THE ID, because the address is what the
        # recipient consented to. If the Owner edited the row to point somewhere else
        # after the link was sent, the old link must not confirm the new address — the
        # person who received it never agreed to that one. Both facts are inside the
        # signature, so a mismatch means the row is no longer what the token described.
        if recipient is None or recipient.email != email or recipient.user_id is not None:
            return None, {
                "title": "This link is no longer valid",
                "message": (
                    "The address it points at is not on the list any more. If that is "
                    "unexpected, ask whoever added you to add it again."
                ),
            }
        return recipient, None

    def _page(self, request, *, title, message, can_confirm=False, button_label="",
              status=200):
        return render(
            request,
            self.template_name,
            {
                "title": title,
                "message": message,
                "can_confirm": can_confirm,
                "button_label": button_label,
            },
            status=status,
        )
