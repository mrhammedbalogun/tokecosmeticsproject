import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel


class Cart(TimeStampedModel):
    KIND_CHOICES = [("standard", "Standard"), ("express", "Express (Buy Now)")]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("converted", "Converted"),
        ("abandoned", "Abandoned"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.CASCADE, related_name="carts",
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="standard")
    country = models.ForeignKey("core.Country", on_delete=models.PROTECT)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="active")
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # At most one active cart per (user, kind). Guests (user NULL) are exempt
            # — their identity is the cart UUID itself, so they can hold many.
            models.UniqueConstraint(
                fields=["user", "kind"],
                condition=Q(status="active", user__isnull=False),
                name="uniq_active_cart_per_user_kind",
            )
        ]

    def __str__(self) -> str:
        who = self.user_id or "guest"
        return f"Cart {self.id} ({who}/{self.kind}/{self.status})"


class CartComboGroup(TimeStampedModel):
    """One combo, sitting in one cart, `quantity` times over.

    IT IS A GROUP HEADER, NOT A LINE. The goods are still ordinary `CartItem` rows —
    one per component variant, each pointing back here — because everything downstream
    of the cart (stock reservation, delivery quoting, the waybill, `OrderItem`) speaks
    `(variant, quantity)` and must keep speaking it. What this row adds is the two facts
    those lines cannot carry between them: WHICH combo they came from, and how many of
    it the shopper wanted.

    Quantity lives here rather than on the lines because a combo is bought whole. A
    shopper who wants two Glow Kits changes ONE number; the component lines are rewritten
    from it (`carts.services.set_combo_quantity`). Letting the lines drift apart would
    produce a "combo" containing three of one thing and two of another, priced as a
    combo, which is not a thing the shop sells.
    """

    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="combo_groups")
    # CASCADE: deleting a combo outright takes its cart lines with it. That is the honest
    # outcome — the price those lines were grouped under no longer exists, and leaving
    # them behind would silently convert a discounted bundle into full-price singles in
    # somebody's basket. Archiving (the normal way to retire a combo) touches nothing.
    combo = models.ForeignKey("combos.Combo", on_delete=models.CASCADE, related_name="cart_groups")
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            # ONE GROUP PER COMBO PER CART, enforced by the database rather than by
            # `add_combo` alone. That function does `select_for_update()` before
            # deciding whether to create — but a `SELECT ... FOR UPDATE` that matches NO
            # ROW locks nothing, so two concurrent adds of the same bundle (a
            # double-tapped button is enough) both saw "no group" and both created one.
            # The shopper then gets two identical cards to reconcile, and the second one
            # is invisible to `add_combo`'s merge for ever after.
            models.UniqueConstraint(
                fields=["cart", "combo"], name="uniq_cart_combo_group"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity}x {self.combo_id} in {self.cart_id}"


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.CASCADE)
    # Null for an ordinary line. Set means this row is part of a combo and must never be
    # edited on its own — `carts.services` scopes every standalone mutation to
    # `combo_group__isnull=True` for exactly that reason.
    combo_group = models.ForeignKey(
        CartComboGroup, null=True, blank=True, on_delete=models.CASCADE, related_name="items"
    )
    quantity = models.PositiveIntegerField(default=1)
    # Snapshot of the resolved price when the item was last added/updated.
    # For drift display only — checkout recomputes. Never the charge basis.
    unit_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    added_at = models.DateTimeField(auto_now=True)

    class Meta:
        # TWO PARTIAL UNIQUES, NOT `unique_together`, and the split is the whole point of
        # the combo work in this file. The same variant can legitimately appear twice in
        # one cart — once bought on its own, once as part of a bundle — and those two
        # rows must stay apart or merging them would either dissolve the combo or
        # silently discount the single.
        #
        # A plain `unique_together("cart", "variant", "combo_group")` would NOT do this:
        # in Postgres two NULLs are never equal, so every standalone line would be
        # unique against every other and the same product could be added to the bag ten
        # times as ten rows. Hence the `IS NULL` half, written out explicitly.
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "variant"],
                condition=Q(combo_group__isnull=True),
                name="uniq_standalone_cart_line",
            ),
            models.UniqueConstraint(
                fields=["combo_group", "variant"],
                condition=Q(combo_group__isnull=False),
                name="uniq_combo_cart_line",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quantity}× {self.variant.sku} in {self.cart_id}"
