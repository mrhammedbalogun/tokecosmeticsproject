"""`notify_staff` — the one way anything in this codebase emails the people who run the
shop, as opposed to the people who buy from it.

ONE MESSAGE PER RECIPIENT, never one message with several addresses in `to`. Three
reasons, in order of how badly each bites:

1. **The recipient list is not public.** `to` is visible to everyone it reaches, so a
   single multi-address send hands an external bookkeeper the Owner's address, every
   subscribed manager's address, and the warehouse's — a list nobody agreed to publish.
   Standalone rows (see `models.NotificationRecipient`) make this a real disclosure, not
   a theoretical one.
2. **One bad address must not silence the rest.** `send.send_email` builds a single
   `EmailMultiAlternatives` and calls `.send()` once; a hard rejection on one address
   fails that call. Fanned out, a stale address costs one retry cycle in Celery and the
   other four people still learn there is an order to pack.
3. **Retries stay proportionate.** `send_email_task` retries the whole task; retrying a
   five-address message because the fifth bounced re-delivers four duplicates.

FAILURE IS NEVER THE CALLER'S PROBLEM. The order callers run this from a post-commit hook
(`apps/orders/state.py`); the low-stock and wallet callers run it from inside a Celery
beat task. In both cases the enqueue is wrapped so a broker outage cannot turn "the
customer paid" into a 500 or kill a scheduled sweep. An order that exists with nobody
told is recoverable — the admin queue still shows it; an order rolled back because Redis
blinked is not.

NOT AUDITED. The audit log is the camera on *staff actions* (`apps/core/audit.py`); a
mail the system sent itself is not one. What IS audited is every edit to the recipient
list, at `admin_views.py`, which is the decision a human actually makes.
"""
from __future__ import annotations

import logging

from apps.notifications.events import EVENTS_BY_CODE
from apps.notifications.models import resolve_recipients
from apps.notifications.tasks import send_email_task

logger = logging.getLogger(__name__)


def notify_staff(event: str, context: dict) -> int:
    """Email everyone subscribed to `event`. Returns how many messages were ACTUALLY
    enqueued — 0 if nobody is subscribed, and fewer than the subscriber count if the
    broker refused some of them.

    THE RETURN VALUE IS LOAD-BEARING FOR THE BEAT TASKS. `low_stock_digest` and
    `monitor_gig_wallet` are edge-triggered: each records "I have told them about this"
    in a `SiteSetting` and then stays quiet until the situation CHANGES. Before this
    module they called `send_email` synchronously, so a failure raised, the state row was
    never written, and the next beat run retried. Returning a count they can gate on is
    what preserves that self-healing property now that sending is asynchronous — without
    it, a broker blip during the one run that crosses the threshold loses the alert until
    the wallet recovers and dips again, which for the wallet means the packing bench
    stops with nobody told. That is the exact failure this whole feature exists to end,
    and it would have been reintroduced in the two events it was built to rescue.

    `context` must be JSON-serialisable — it crosses into Celery — and the template named
    by `event`'s registry entry must exist. Both are pinned by `test_events.py`.
    """
    registered = EVENTS_BY_CODE.get(event)
    if registered is None:
        # A caller naming an event that does not exist is a programming error, and the
        # test suite catches it. At runtime the useful behaviour is to say so loudly and
        # carry on: the alternative is raising inside a post-commit hook, where the
        # exception cannot roll anything back and only obscures the real work.
        logger.error("notify_staff: %s is not a registered event", event)
        return 0

    addresses = resolve_recipients(event)
    if not addresses:
        # Deliberately not a warning. "Nobody subscribed" is a configuration a person
        # chose, and an alert that fires on every single order until someone edits a
        # screen is an alert people learn to filter. The visible version of this warning
        # is on the admin screen, next to the event it applies to.
        logger.info("notify_staff: no recipients for %s", event)
        return 0

    enqueued = 0
    for address in addresses:
        try:
            send_email_task.delay(registered.template, address, context)
        except Exception:  # noqa: BLE001 — broker down, see module docstring
            logger.exception("notify_staff: could not enqueue %s to %s", event, address)
        else:
            enqueued += 1
    return enqueued
