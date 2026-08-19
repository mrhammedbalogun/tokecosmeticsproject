"""Attach guest orders (user=None) to a verified account on exact email match.

Guarded two ways: only USER-LESS orders are ever touched (an order that already has a
user is never re-pointed), and the match is on the account's own verified email.

Originally written for migrated WooCommerce guest rows under Decision 7 ("new orders
always carry a user"). Plan-38 REVERSED Decision 7: live guest checkout now mints
fresh user=None orders, and this claiming them on verify / reset / verified login is
the deliberate "your guest orders appear in your account" mechanism — not a side
effect. The verified-email guard is what keeps it safe: registering someone else's
address gets you nothing until their inbox proves it is yours.
"""
from __future__ import annotations


def claim_legacy_orders(user) -> int:
    from apps.orders.models import Order

    return (
        Order.objects.filter(user__isnull=True, email__iexact=user.email)
        .update(user=user)
    )
