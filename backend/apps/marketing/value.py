"""What number goes in `value` on a Purchase, and in what currency.

Every one of the four platforms optimises delivery against this number, so it is not a
reporting detail — it decides which customers the ad platforms go and look for. It is
computed in ONE place so that Meta, TikTok, Snapchat and GA4 can never disagree about
what an order was worth.

── THE TWO BASES ───────────────────────────────────────────────────────────────────────

`MarketingSettings.purchase_value_basis` picks between them:

  goods (default)  Net sales — goods after every discount, excluding shipping and tax.
  grand_total      Everything the customer was charged.

── WHY `goods` BORROWS THE REFERRAL BASE ───────────────────────────────────────────────

`referrals.services.commission_base` already computes "net sales" for this shop, and its
docstring is where the subtle half is argued out: for a `prices_include_tax` market
(Nigeria) the VAT is INSIDE `subtotal` and must be subtracted, while for GB/US/CA it was
added on top and must not be — and since Plan-37 the amount to subtract is
`tax_total - delivery_tax_total`, because a market may tax freight too.

Duplicating that branch here was the alternative and it was rejected: the branch is
exactly the part that would be got wrong twice, and the two would drift on the hard case
rather than the easy one. The cost of borrowing is a coupling that must be said out loud:

    **If the referral programme's definition of net sales ever changes, the number
    reported to the ad platforms changes with it.** That is currently correct — both
    mean "what the shop earned on the goods" — and if they ever need to diverge, this is
    the function to fork, not `commission_base`.

`tests/test_value.py` pins the agreement, so a change to one without the other fails.
"""
from __future__ import annotations

from decimal import Decimal


def purchase_value(order) -> Decimal:
    """The order's value for an ad platform, in the order's own currency."""
    from apps.marketing.models import MarketingSettings

    if MarketingSettings.load().purchase_value_basis == "grand_total":
        return Decimal(order.grand_total)

    from apps.referrals.services import commission_base

    return commission_base(order)


def currency_code(order) -> str:
    """ISO-4217, upper case. `Currency`'s primary key IS the code, so this reads the FK
    id and never loads the row — the Purchase task runs once per paid order and has no
    business doing a join to learn a three-letter string it already holds."""
    return (order.currency_id or "").upper()
