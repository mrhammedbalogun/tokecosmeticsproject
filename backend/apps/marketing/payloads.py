"""The vendor-neutral shape of a conversion event, built once and translated four ways.

Four platforms, four spellings of the same facts. `ViewContent` is `VIEW_CONTENT` at
Snapchat and `view_item` at GA4; a purchase's value is a JSON number at Meta, a string at
Snapchat, and lives under `params` at GA4. Building each vendor's body straight from an
`Order` would mean four places that know how to read an order, and four places to fix
when one of them is wrong.

So: read the order ONCE into these dataclasses, then let each adapter translate. The
adapters are then pure functions of a `ConversionPayload`, which is what makes them
testable without a database.

The canonical event vocabulary — deliberately small, and deliberately ours:

    page_view · view_content · add_to_cart · initiate_checkout · purchase

Each adapter owns the translation to its vendor's spelling. Nothing outside an adapter
may use a vendor's name for an event.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

PAGE_VIEW = "page_view"
VIEW_CONTENT = "view_content"
ADD_TO_CART = "add_to_cart"
INITIATE_CHECKOUT = "initiate_checkout"
PURCHASE = "purchase"

CANONICAL_EVENTS = frozenset(
    {PAGE_VIEW, VIEW_CONTENT, ADD_TO_CART, INITIATE_CHECKOUT, PURCHASE}
)


@dataclass(frozen=True)
class ContentItem:
    """One line of the order or cart.

    `content_id` is the SKU, and that choice is load-bearing across the whole plan: the
    product feed (`apps/marketing/feed.py`), the browser pixel and this payload must all
    name a product the SAME way or dynamic retargeting silently does nothing. A mismatch
    produces no error anywhere — the ads simply stop showing the product the visitor
    looked at.
    """

    content_id: str
    quantity: int
    item_price: Decimal
    name: str = ""
    brand: str = ""
    category: str = ""


@dataclass(frozen=True)
class UserSignals:
    """Everything that helps a platform recognise the person, in RAW form.

    Raw, not hashed: hashing is each adapter's job, because the adapters disagree about
    which fields to send and about whether a hash goes in a list or a bare string. One
    pre-hashed blob would have to satisfy all four and would end up sending fields to
    platforms that never asked for them.

    The click ids and cookies are NEVER hashed by anyone — see `hashing.py`'s docstring.
    """

    email: str = ""
    phone: str = ""
    first_name: str = ""
    last_name: str = ""
    city: str = ""
    state: str = ""
    postcode: str = ""
    country: str = ""
    # A stable per-customer id, hashed before sending. The user's primary key for an
    # account holder; the empty string for a guest, who by definition has no stable id
    # to give (their email is the only identifier they have, and it is already sent).
    external_id: str = ""
    client_ip: str = ""
    client_user_agent: str = ""
    # {"fbclid": ..., "ttclid": ..., "sccid": ..., "gclid": ...}
    click_ids: dict[str, str] = field(default_factory=dict)
    # {"fbp": ..., "fbc": ..., "ttp": ..., "scid": ...}
    pixel_cookies: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversionPayload:
    """One event, ready to be translated for any vendor."""

    event_name: str          # one of CANONICAL_EVENTS
    event_id: str            # shared with the browser tag; the dedup key
    event_time: int          # Unix SECONDS. GA4 wants microseconds and converts its own.
    source_url: str = ""
    currency: str = ""
    value: Decimal = Decimal("0")
    order_number: str = ""
    contents: tuple[ContentItem, ...] = ()
    user: UserSignals = field(default_factory=UserSignals)
    # GA4 needs a client_id that ties the server event to the browser session. Absent
    # for a webhook-driven purchase, in which case the adapter synthesises one — see
    # `channels/ga4.py`, which explains what that costs.
    ga_client_id: str = ""
