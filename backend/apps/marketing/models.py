"""Ad-platform measurement: what is switched on, what a visitor consented to, and the
outbox of events owed to Meta, TikTok, Snapchat and Google (Plan-44).

Four tables, and each exists for a reason the others cannot serve:

  MarketingSettings   ONE row. The master switch, the consent policy, and the one
                      business decision in here (what `value` on a Purchase means).
  MarketingChannel    One row per ad platform. Public ids and switches ONLY — access
                      tokens are env-backed, see `credentials.py`.
  OrderAttribution    What the browser knew at the moment an order was placed, frozen.
                      The server-side Purchase runs from a payment webhook and has no
                      browser behind it; this row is the only thing it can read.
  ConversionEvent     The outbox. One row per (channel, event) with a unique key, so a
                      retry can never bill the same purchase to an ad platform twice.
"""
from __future__ import annotations

from django.db import models

from apps.core.models import TimeStampedModel

# The four channels the shop advertises on, plus GA4. Instagram is DELIBERATELY ABSENT
# and its absence is the single most common misunderstanding about this app: Instagram
# ads are bought through Meta and optimise against the SAME Meta dataset as Facebook.
# There is no Instagram pixel to install. Adding an "instagram" row here would create a
# second dataset that no ad account reads.
CHANNEL_CHOICES = [
    ("meta", "Meta (Facebook + Instagram)"),
    ("tiktok", "TikTok"),
    ("snapchat", "Snapchat"),
    ("google_ads", "Google Ads"),
    ("ga4", "Google Analytics 4"),
]
CHANNEL_CODES = frozenset(code for code, _ in CHANNEL_CHOICES)

# The EEA plus the UK: the markets where a non-essential cookie needs consent BEFORE it
# is set, rather than an opt-out afterwards. Seeded into MarketingSettings rather than
# frozen here, because whether Nigeria joins this list under the NDPA 2023 is Hammed's
# call to make on a Tuesday, not a deploy.
DEFAULT_CONSENT_REQUIRED = [
    "GB", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IS", "IE", "IT", "LV", "LI", "LT", "LU", "MT", "NL", "NO", "PL", "PT",
    "RO", "SK", "SI", "ES", "SE",
]


def _default_consent_countries() -> list[str]:
    """A callable default: a mutable list literal would be SHARED by every row that
    takes the default, and an admin edit to one would silently edit the class."""
    return list(DEFAULT_CONSENT_REQUIRED)


class MarketingSettings(models.Model):
    """ONE row, pk forced to 1 — the `StoreSettings` shape, for the same reasons: the
    Owner flips these at runtime, they must survive a restart, and a second row would
    mean two answers to "is tracking on".

    ── THE MASTER SWITCH ───────────────────────────────────────────────────────────────

    `tracking_enabled = False` stops everything: no pixel is served to a browser, no
    server event is queued, and the consent banner stops being shown (there is nothing
    left to consent to). It exists because the fastest correct response to "a pixel is
    doing something we did not intend" is one checkbox, not a deploy.

    ── WHAT `value` MEANS ON A PURCHASE ────────────────────────────────────────────────

    The one genuine business decision in this app. Every ad platform optimises on the
    number we call `value`, so the choice changes which customers the platforms go and
    find:

      goods (default) — net sales: the goods after every discount, excluding shipping
                        and tax. This is what the shop actually earns from the sale, and
                        it is the same definition the referral programme already pays on
                        (`referrals.services.commission_base`).
      grand_total     — everything the customer was charged, freight and tax included.
                        Flatters ROAS and is what some agencies expect to see.

    Configurable rather than decided here because an agency arriving with a reporting
    standard is a marketing decision, and neither answer is wrong.
    """

    VALUE_BASIS = [("goods", "Net goods (after discounts, excl. shipping and tax)"),
                   ("grand_total", "Grand total (incl. shipping and tax)")]

    tracking_enabled = models.BooleanField(default=True)
    purchase_value_basis = models.CharField(max_length=16, choices=VALUE_BASIS, default="goods")

    # ISO-3166 alpha-2 codes where consent must be GIVEN before anything is stored.
    # Outside this list the banner still shows and withdrawal still works; the default
    # is simply the other way round. See `apps/marketing/consent.py`.
    consent_required_countries = models.JSONField(default=_default_consent_countries)

    # Bumped when the set of channels changes materially, which re-asks everyone who
    # answered the older question. A visitor consented to the pixels we listed, not to
    # a list we extended afterwards — that is what makes the record worth keeping.
    consent_version = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name_plural = "marketing settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "MarketingSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return f"marketing settings (tracking {'on' if self.tracking_enabled else 'off'})"


class MarketingChannel(TimeStampedModel):
    """One ad platform's configuration. **Public identifiers only.**

    ── WHY THERE IS NO `access_token` COLUMN ───────────────────────────────────────────

    A pixel id is public: it is in the HTML of every page, and anyone can read it with
    View Source. A Conversions API token is not — it can write events into the shop's ad
    account, and on some platforms read from it. It therefore lives exactly where every
    payment gateway secret in this codebase already lives: an environment variable on the
    server, listed in `credentials.py`, reported to the admin screen as configured or
    not configured and NEVER rendered back.

    The cost is real and should be stated: switching a channel on needs an env edit and a
    container restart, which is a deploy-shaped act, not an admin-screen act. That is the
    same cost `PAYSTACK_SECRET_KEY` already imposes, and it buys the property that a
    read-only leak of this table (a stray API response, a database dump in a support
    thread) hands over nothing but numbers that were public anyway.

    ── THE TWO SWITCHES ────────────────────────────────────────────────────────────────

    `browser_enabled` and `server_enabled` are separate because they fail separately and
    are diagnosed separately. When conversions look wrong, the first question is always
    "which half is lying" — and the answer is found by turning one off. Turning the whole
    channel off to answer it would lose the comparison.
    """

    code = models.CharField(max_length=20, choices=CHANNEL_CHOICES, unique=True)
    is_enabled = models.BooleanField(default=False)

    # The public id the browser tag needs: Meta dataset/pixel id, TikTok pixel code,
    # Snap pixel id, Google Ads conversion id ("AW-123456789"), GA4 measurement id.
    pixel_id = models.CharField(max_length=100, blank=True)

    # Only Google Ads uses this: the conversion LABEL, the second half of the
    # `send_to: "AW-123/AbC-D_efG"` pair. Left blank everywhere else rather than given a
    # channel-specific name, because a JSON blob of "extra settings" is how a config
    # table stops being readable.
    secondary_id = models.CharField(max_length=100, blank=True)

    # ── THE SERVER SIDE'S OWN ADDRESSING (Plan-44b) ────────────────────────────────
    #
    # Meta, TikTok and Snapchat all send server events to the SAME id the browser tag
    # uses — one pixel, two halves. Google Ads does not: the browser tag is addressed by
    # `AW-…` + a conversion label, while the Data Manager API is addressed by the
    # advertiser's 10-digit customer id and a numeric conversion ACTION id. Four values
    # for one channel.
    #
    # Two explicit columns rather than a JSON "extra settings" blob, which is how a
    # config table stops being readable — and named generically rather than
    # `google_customer_id`, because the shape (which account, which destination inside
    # it) is not unique to Google.
    #
    # Blank for every other channel, and the admin screen only offers them where they
    # mean something.
    server_account_id = models.CharField(max_length=64, blank=True)
    server_destination_id = models.CharField(max_length=64, blank=True)

    browser_enabled = models.BooleanField(default=True)
    server_enabled = models.BooleanField(default=True)

    # Routes events to the platform's test console instead of the live dataset. MUST be
    # cleared before a real campaign reads the numbers — every vendor says so, and a
    # forgotten test code is a silent zero in the ad account. The admin screen warns.
    test_event_code = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.get_code_display()} ({'on' if self.is_enabled else 'off'})"


class OrderAttribution(models.Model):
    """What the browser knew when the order was placed, frozen at placement.

    ── WHY THIS IS A SNAPSHOT AND NOT A LOOKUP ─────────────────────────────────────────

    The same argument `Order.referral_code` makes, and for the same machinery. The
    server-side Purchase fires from `orders.state._effects_for("processing")`, which is
    reached from a payment webhook: no browser, no cookie jar, no client IP, no user
    agent. Anything not written down at checkout is simply gone by the time the money is
    confirmed.

    ── WHY CONSENT IS IN HERE ──────────────────────────────────────────────────────────

    A customer may withdraw consent between placing an order and the gateway confirming
    it, and the lawful basis for sending the event is the state at COLLECTION. Reading a
    live consent cookie at webhook time would be reading the wrong thing at the wrong
    moment, from a request that has no cookie anyway. It is also the only auditable
    answer to "why was this event sent" months later.

    A row with `consent_marketing = False` is still written. It records that the order
    happened and was deliberately NOT reported — which is a different fact from an order
    nobody ever looked at, and the difference matters when purchases go missing from an
    ad account and somebody has to explain the gap.
    """

    order = models.OneToOneField(
        "orders.Order", on_delete=models.CASCADE, related_name="marketing_attribution"
    )

    consent_marketing = models.BooleanField(default=False)
    consent_analytics = models.BooleanField(default=False)
    consent_version = models.PositiveIntegerField(default=0)

    # {"fbclid": "...", "ttclid": "...", "sccid": "...", "gclid": "..."} — the ad click
    # that brought them, captured by the storefront proxy from the landing URL.
    click_ids = models.JSONField(default=dict, blank=True)
    # {"fbp": "fb.1...", "fbc": "fb.1...", "ttp": "...", "scid": "..."} — the pixels'
    # own first-party cookies, read out of the jar by the checkout BFF. Present only
    # when the pixel actually loaded, which is why the click ids above are captured
    # independently: an ad blocker kills the cookie, not the click id.
    pixel_cookies = models.JSONField(default=dict, blank=True)

    # Both are required by every platform's match algorithm and both are personal data.
    # `apps.marketing.tasks.purge_attribution_pii` clears these two columns after the
    # last platform's attribution window has closed; the click ids stay, because they
    # identify an ad click rather than a person.
    client_ip = models.GenericIPAddressField(null=True, blank=True)
    client_user_agent = models.TextField(blank=True)

    # The page the order was placed from. Meta and Snap both take it, and Meta's event
    # match quality drops without it.
    event_source_url = models.URLField(max_length=1000, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    pii_purged_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"attribution for {self.order_id}"


class ConversionEvent(TimeStampedModel):
    """The outbox: one row per (channel, event), delivered by Celery, retried on failure.

    ── WHY AN OUTBOX AND NOT A BARE HTTP CALL ──────────────────────────────────────────

    Three things a direct call cannot do. It cannot survive Meta returning a 500 while a
    customer's money is already taken. It cannot be READ six months later when the ad
    account and the order list disagree and somebody must find out which is wrong. And it
    cannot promise that a retried Celery task does not report the same purchase twice —
    the platforms dedupe on `event_id`, but only within their own window, and a duplicate
    that lands outside it is a real double-count.

    The unique constraint below is what makes the third one true on our side, before any
    network call happens.

    ── STATUSES ────────────────────────────────────────────────────────────────────────

      pending  queued, not yet attempted
      sent     the platform accepted it
      failed   attempts exhausted; `last_error` says why. A human decision from here.
      skipped  deliberately not sent — no consent, channel off, nothing configured.
               A recorded non-send, which is why it is a status and not a missing row.
    """

    STATUSES = [("pending", "Pending"), ("sent", "Sent"),
                ("failed", "Failed"), ("skipped", "Skipped")]

    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    # Our canonical vocabulary ("purchase"), not the platform's. Each adapter translates:
    # Meta says Purchase, TikTok says CompletePayment, Snap says PURCHASE. Storing ours
    # keeps the table readable and keeps a vendor rename out of historical rows.
    event_name = models.CharField(max_length=50)
    # The SAME string the browser tag sends, which is how the platform knows the two
    # halves are one event. For a purchase it is the order number.
    event_id = models.CharField(max_length=100)

    order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="conversion_events",
    )

    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)
    # Truncated: a vendor error body can be a page of HTML from a CDN, and this table is
    # read by humans looking for a reason, not by a parser.
    response_excerpt = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # The idempotency guarantee, enforced by Postgres rather than by remembering
            # to check. Re-running the paid effect (a webhook redelivery, a replayed
            # Celery task, an admin re-confirming a payment) hits this and does nothing.
            models.UniqueConstraint(
                fields=["channel", "event_name", "event_id"],
                name="marketing_conversion_event_once",
            ),
        ]
        indexes = [
            # The retry sweep and the admin list both ask "what is not sent yet".
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.channel}/{self.event_name}/{self.event_id} ({self.status})"
