"""The free gifts an order owes, read back off its own lines.

ONE READER FOR THREE DOCUMENTS — the invoice, the customer's confirmation and the staff
alert. A gift is not a priced line and not a stock row: it exists as a sentence, snapshot
on `OrderItem.combo_gift`, and the only thing standing between that sentence and a parcel
that goes out without it is the paperwork. Three separate implementations of "what did we
promise" is how two of them end up saying different things.

DE-DUPLICATED IN LINE ORDER. The snapshot is written on EVERY line of a gift bundle — a
four-product box repeats its gift four times — and an order holding two different gift
bundles owes both, once each.
"""


def order_gifts(order) -> list[str]:
    """["Free Kids Hair Grow Cream (50ml)"] — empty for an order that promised nothing."""
    return list(dict.fromkeys(item.combo_gift for item in order.items.all() if item.combo_gift))
