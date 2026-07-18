"""Attach migrated guest orders (user=None) to a verified account on exact email match.

Guarded two ways: only USER-LESS orders are ever touched (an order that already has a
user is never re-pointed), and the match is on the account's own verified email. New
orders always carry a user (Decision 7), so this only ever picks up legacy guest rows.
"""
from __future__ import annotations


def claim_legacy_orders(user) -> int:
    from apps.orders.models import Order

    return (
        Order.objects.filter(user__isnull=True, email__iexact=user.email)
        .update(user=user)
    )
