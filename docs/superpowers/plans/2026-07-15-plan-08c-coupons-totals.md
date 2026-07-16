# Plan-08c — Coupons & Totals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Runs on PostgreSQL. Run tests with `uv run python -m pytest` from `backend/`.

**Goal:** A coupon model + validation service returning a discount or a specific error code, and `compute_totals` — the single source of truth for subtotal / discount / delivery / tax / grand total, used by cart display, checkout, and order creation.

**Architecture (per Fable 5 consult):** `apps.checkout` holds pure domain logic — no HTTP, no Cart import. `compute_totals(items, country, delivery_amount, coupon)` takes an iterable of `(variant, qty)`, re-resolves each line via `pricing.services.resolve_price` (never trusts a snapshot), rounds **half-up per line then sums**, and applies discount → delivery adjustment → tax in that order. Tax follows the country: `prices_include_tax` → tax is the extracted portion (informational, already in the price); else it's added on top. `validate_coupon` is a separate gate returning eligibility + the coupon; `compute_totals` consumes an already-valid coupon so totals and validation never diverge.

**Tech Stack:** Django 5.2, DRF, PostgreSQL, `decimal` with `ROUND_HALF_UP`. No new dependencies.

> **Part of the Plan-08 split:** 08a carts ∥ 08b delivery ∥ **08c coupons+totals** → 08d checkout. 08c is independent of 08a/08b.
>
> **Deviation from the master spec (Fable-approved, same decoupling rationale as 08b):** `CouponRedemption` uses a soft `order_number` CharField instead of a `FK(orders.Order)`, because `Order` is built in 08d and 08c must stay independent. The Order→Coupon link still exists via `Order.coupon` (Plan-10). `compute_totals` takes a resolved `delivery_amount: Decimal` (computed by the caller via 08b) rather than a `delivery_option`+`address`, so 08c never imports `apps.delivery`.
>
> **MVP simplification (documented):** a coupon's `applies_to` (products/categories) acts as an **eligibility gate** — the cart must contain ≥1 matching item — and the discount then applies to the whole subtotal. Per-line targeted discounts are a post-launch refinement. Recorded in docs/architecture.md.

---

## Conventions

- New Django app `apps.checkout`. Add to `INSTALLED_APPS` after `apps.delivery`.
- Every money value is `Decimal`, quantized to `Country.currency.decimal_places` (2 for all launch currencies) with `ROUND_HALF_UP`. A single `q2()` helper enforces this.
- Coupon codes are stored uppercased; lookup is case-insensitive.

## File Structure

**Created:**
- `backend/apps/checkout/__init__.py`, `apps.py`, `models.py`, `factories.py`
- `backend/apps/checkout/services/__init__.py`, `coupons.py`, `totals.py`
- `backend/apps/checkout/migrations/__init__.py`, `0001_initial.py` (generated)
- `backend/apps/checkout/tests/__init__.py`, `test_coupon_validation.py`, `test_totals.py`

**Modified:**
- `backend/config/settings/base.py` (INSTALLED_APPS)
- `docs/architecture.md`

*(No URLs in 08c — coupons are applied through the cart/checkout endpoints in 08d; the admin coupon CRUD is Plan-19.)*

---

## Task 1: Coupon + CouponRedemption models

**Files:**
- Create: `backend/apps/checkout/__init__.py` (empty), `apps.py`, `models.py`, `factories.py`
- Create: `backend/apps/checkout/migrations/__init__.py` (empty)
- Modify: `backend/config/settings/base.py`
- Test: `backend/apps/checkout/tests/__init__.py` (empty), a smoke in Task 2

- [ ] **Step 1: App config + register**

Create `backend/apps/checkout/apps.py`:

```python
from django.apps import AppConfig


class CheckoutConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.checkout"
```

Add `"apps.checkout",` to `INSTALLED_APPS` (after `"apps.delivery",`).

- [ ] **Step 2: Write the models**

Create `backend/apps/checkout/models.py`:

```python
from django.conf import settings
from django.db import models
from django.db.models.functions import Upper

from apps.core.models import TimeStampedModel


class Coupon(TimeStampedModel):
    TYPE_CHOICES = [
        ("percent", "Percentage off"),
        ("fixed", "Fixed amount off"),
        ("free_shipping", "Free shipping"),
    ]

    code = models.CharField(max_length=40)  # stored uppercased; CI-unique via constraint below
    type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # % or amount
    currency = models.ForeignKey(
        "core.Currency", null=True, blank=True, on_delete=models.PROTECT
    )  # required for fixed; null for percent/free_shipping
    min_subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True)  # total, null = unlimited
    usage_limit_per_user = models.PositiveIntegerField(null=True, blank=True)
    applies_to_products = models.ManyToManyField("catalog.Product", blank=True)
    applies_to_categories = models.ManyToManyField("catalog.Category", blank=True)
    is_active = models.BooleanField(default=True)
    legacy_source = models.CharField(max_length=20, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(Upper("code"), name="uniq_coupon_code_ci"),
        ]

    def __str__(self) -> str:
        return self.code


class CouponRedemption(TimeStampedModel):
    """Usage ledger. `order_number` is a soft reference (not an FK) so this app stays
    independent of apps.orders (built in 08d); 08d writes a row per successful order."""

    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    email = models.EmailField(blank=True)
    order_number = models.CharField(max_length=20, blank=True, db_index=True)

    def __str__(self) -> str:
        return f"{self.coupon.code} by {self.email or self.user_id} ({self.order_number})"
```

- [ ] **Step 3: Save-normalise the code (uppercase)**

Add to `Coupon`:

```python
    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)
```

- [ ] **Step 4: Factory**

Create `backend/apps/checkout/factories.py`:

```python
import factory

from apps.checkout.models import Coupon


class CouponFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Coupon

    code = factory.Sequence(lambda n: f"SAVE{n}")
    type = "percent"
    value = "10.00"
    is_active = True
```

- [ ] **Step 5: Migrate**

Run: `uv run python manage.py makemigrations checkout`
Expected: creates `0001_initial.py` (Coupon, CouponRedemption).
Run: `uv run python manage.py migrate checkout`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add apps/checkout config/settings/base.py
git commit -m "feat(checkout): Coupon + CouponRedemption models (CI-unique code)"
```

---

## Task 2: Coupon validation service

**Files:**
- Create: `backend/apps/checkout/services/__init__.py` (empty), `coupons.py`
- Test: `backend/apps/checkout/tests/test_coupon_validation.py`

Error codes returned (never raise for the normal invalid cases — return a result the API maps to 400): `not_found`, `inactive`, `not_started`, `expired`, `min_not_met`, `wrong_currency`, `exhausted`, `user_exhausted`, `not_valid_for_items`.

- [ ] **Step 1: Write the failing tests**

Create `backend/apps/checkout/tests/test_coupon_validation.py`:

```python
import pytest
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone

from apps.checkout.factories import CouponFactory
from apps.checkout.models import CouponRedemption
from apps.checkout.services.coupons import validate_coupon
from apps.core.models import Country, Currency

pytestmark = pytest.mark.django_db


def _ng():
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    return Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)


def test_unknown_code_returns_not_found():
    ng = _ng()
    res = validate_coupon("NOPE", subtotal=Decimal("5000"), country=ng)
    assert not res.ok and res.error_code == "not_found"


def test_case_insensitive_lookup():
    ng = _ng()
    CouponFactory(code="SUMMER", type="percent", value="10.00")
    res = validate_coupon("summer", subtotal=Decimal("5000"), country=ng)
    assert res.ok and res.coupon.code == "SUMMER"


def test_expired_and_not_started():
    ng = _ng()
    now = timezone.now()
    CouponFactory(code="OLD", ends_at=now - timedelta(days=1))
    CouponFactory(code="FUTURE", starts_at=now + timedelta(days=1))
    assert validate_coupon("OLD", Decimal("5000"), ng).error_code == "expired"
    assert validate_coupon("FUTURE", Decimal("5000"), ng).error_code == "not_started"


def test_min_subtotal_not_met():
    ng = _ng()
    CouponFactory(code="BIG", min_subtotal="10000.00")
    assert validate_coupon("BIG", Decimal("5000"), ng).error_code == "min_not_met"


def test_fixed_coupon_wrong_currency():
    ng = _ng()
    gbp = Currency.objects.create(code="GBP", symbol="£")
    CouponFactory(code="TENOFF", type="fixed", value="10.00", currency=gbp)
    # NG cart is NGN; a GBP fixed coupon can't apply.
    assert validate_coupon("TENOFF", Decimal("5000"), ng).error_code == "wrong_currency"


def test_total_usage_exhausted():
    ng = _ng()
    c = CouponFactory(code="ONEUSE", usage_limit=1)
    CouponRedemption.objects.create(coupon=c, email="a@x.com", order_number="TC-1")
    assert validate_coupon("ONEUSE", Decimal("5000"), ng).error_code == "exhausted"


def test_per_user_usage_exhausted(django_user_model):
    ng = _ng()
    user = django_user_model.objects.create_user(email="u@x.com", password="pw")
    c = CouponFactory(code="ONCEPER", usage_limit_per_user=1)
    CouponRedemption.objects.create(coupon=c, user=user, email=user.email, order_number="TC-2")
    res = validate_coupon("ONCEPER", Decimal("5000"), ng, user=user)
    assert res.error_code == "user_exhausted"


def test_applies_to_gate(django_user_model):
    ng = _ng()
    from apps.catalog.factories import ProductFactory
    p1 = ProductFactory(); p2 = ProductFactory()
    c = CouponFactory(code="P1ONLY")
    c.applies_to_products.add(p1)
    # cart has only p2 → not valid
    res = validate_coupon("P1ONLY", Decimal("5000"), ng, item_product_ids={p2.id})
    assert res.error_code == "not_valid_for_items"
    # cart includes p1 → valid
    ok = validate_coupon("P1ONLY", Decimal("5000"), ng, item_product_ids={p1.id, p2.id})
    assert ok.ok
```

> If `ProductFactory` isn't exported from `apps/catalog/factories.py`, use the correct product factory name (check that file).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/checkout/tests/test_coupon_validation.py -v`
Expected: FAIL (`ModuleNotFoundError: apps.checkout.services.coupons`).

- [ ] **Step 3: Implement the validator**

Create `backend/apps/checkout/services/__init__.py` (empty) and `backend/apps/checkout/services/coupons.py`:

```python
"""Coupon eligibility. Returns a CouponValidation — never raises for the normal
'invalid' cases (the API maps error_code → 400). Usage counts read the redemption
ledger; note there's a soft race on the very last use under concurrency (two
checkouts, one remaining use) — acceptable for MVP; the ledger records the truth
and admin can see overuse. Tighten with a locked counter post-launch if needed."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from apps.checkout.models import Coupon, CouponRedemption


@dataclass(frozen=True)
class CouponValidation:
    ok: bool
    error_code: str = ""
    coupon: Coupon | None = None


def _invalid(code: str) -> CouponValidation:
    return CouponValidation(ok=False, error_code=code)


def validate_coupon(
    code: str,
    subtotal: Decimal,
    country,
    user=None,
    email: str = "",
    item_product_ids: set[int] | None = None,
    item_category_ids: set[int] | None = None,
) -> CouponValidation:
    coupon = Coupon.objects.filter(code=(code or "").strip().upper()).first()
    if coupon is None:
        return _invalid("not_found")
    if not coupon.is_active:
        return _invalid("inactive")

    now = timezone.now()
    if coupon.starts_at and now < coupon.starts_at:
        return _invalid("not_started")
    if coupon.ends_at and now > coupon.ends_at:
        return _invalid("expired")

    if subtotal < coupon.min_subtotal:
        return _invalid("min_not_met")

    if coupon.type == "fixed" and coupon.currency_id and coupon.currency_id != country.currency_id:
        return _invalid("wrong_currency")

    if coupon.usage_limit is not None:
        total_used = CouponRedemption.objects.filter(coupon=coupon).count()
        if total_used >= coupon.usage_limit:
            return _invalid("exhausted")

    if coupon.usage_limit_per_user is not None and user is not None:
        used_by_user = CouponRedemption.objects.filter(coupon=coupon, user=user).count()
        if used_by_user >= coupon.usage_limit_per_user:
            return _invalid("user_exhausted")

    # applies_to gate: if the coupon restricts to products/categories, the cart must
    # contain at least one matching item (MVP: discount then applies to whole subtotal).
    restricts_products = coupon.applies_to_products.exists()
    restricts_categories = coupon.applies_to_categories.exists()
    if restricts_products or restricts_categories:
        allowed_products = set(coupon.applies_to_products.values_list("id", flat=True))
        allowed_categories = set(coupon.applies_to_categories.values_list("id", flat=True))
        matched = bool((item_product_ids or set()) & allowed_products) or bool(
            (item_category_ids or set()) & allowed_categories
        )
        if not matched:
            return _invalid("not_valid_for_items")

    return CouponValidation(ok=True, coupon=coupon)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest apps/checkout/tests/test_coupon_validation.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add apps/checkout/services apps/checkout/tests/test_coupon_validation.py
git commit -m "feat(checkout): coupon validation service with typed error codes"
```

---

## Task 3: compute_totals — the single source of truth

**Files:**
- Create: `backend/apps/checkout/services/totals.py`
- Test: `backend/apps/checkout/tests/test_totals.py`

**Order of operations:** subtotal (Σ per-line-rounded) → discount (on subtotal; free_shipping = 0 here) → delivery (given amount, zeroed by a free_shipping coupon) → tax (on `subtotal − discount`, extracted if inclusive else added) → grand_total.

- [ ] **Step 1: Write the failing tests**

Create `backend/apps/checkout/tests/test_totals.py`:

```python
import pytest
from decimal import Decimal

from apps.catalog.factories import ProductVariantFactory
from apps.checkout.factories import CouponFactory
from apps.checkout.services.totals import compute_totals
from apps.core.models import Country, Currency
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _country(include_tax, rate="7.5", code="NG", ccy="NGN"):
    cur = Currency.objects.create(code=ccy, symbol="¤")
    return Country.objects.create(
        code=code, name=code, currency=cur, is_default=(code == "NG"),
        tax_rate_percent=Decimal(rate), prices_include_tax=include_tax,
    )


def _priced_variant(country, amount):
    v = ProductVariantFactory()
    Price.objects.create(variant=v, currency=country.currency, amount=Decimal(amount))
    return v


def test_subtotal_and_inclusive_tax_extraction():
    ng = _country(include_tax=True, rate="7.5")
    v = _priced_variant(ng, "1075.00")
    t = compute_totals([(v, 2)], ng)
    assert t.subtotal == Decimal("2150.00")
    # tax = 2150 - 2150/1.075 = 150.00
    assert t.tax == Decimal("150.00")
    assert t.grand_total == Decimal("2150.00")  # inclusive: tax already inside subtotal
    assert t.currency == "NGN"


def test_exclusive_tax_added_on_top():
    us = _country(include_tax=False, rate="10", code="US", ccy="USD")
    v = _priced_variant(us, "100.00")
    t = compute_totals([(v, 1)], us)
    assert t.subtotal == Decimal("100.00")
    assert t.tax == Decimal("10.00")
    assert t.grand_total == Decimal("110.00")


def test_percent_coupon_discount():
    ng = _country(include_tax=True)
    v = _priced_variant(ng, "1000.00")
    c = CouponFactory(type="percent", value="10.00")
    t = compute_totals([(v, 1)], ng, coupon=c)
    assert t.discount == Decimal("100.00")
    assert t.grand_total == Decimal("900.00")


def test_fixed_coupon_discount_not_below_zero():
    ng = _country(include_tax=True)
    v = _priced_variant(ng, "500.00")
    c = CouponFactory(type="fixed", value="800.00", currency=ng.currency)
    t = compute_totals([(v, 1)], ng, coupon=c)
    assert t.discount == Decimal("500.00")  # capped at subtotal
    assert t.grand_total == Decimal("0.00")


def test_delivery_added_and_free_shipping_coupon_zeroes_it():
    ng = _country(include_tax=True)
    v = _priced_variant(ng, "1000.00")
    t = compute_totals([(v, 1)], ng, delivery_amount=Decimal("1500.00"))
    assert t.delivery == Decimal("1500.00")
    assert t.grand_total == Decimal("2500.00")

    fs = CouponFactory(type="free_shipping", value="0")
    t2 = compute_totals([(v, 1)], ng, delivery_amount=Decimal("1500.00"), coupon=fs)
    assert t2.delivery == Decimal("0.00")
    assert t2.discount == Decimal("0.00")
    assert t2.grand_total == Decimal("1000.00")


def test_per_line_half_up_rounding():
    ng = _country(include_tax=False, rate="0")
    v = _priced_variant(ng, "0.125")  # rounds half-up to 0.13 per unit
    t = compute_totals([(v, 1)], ng)
    assert t.subtotal == Decimal("0.13")


def test_unpriced_line_raises():
    ng = _country(include_tax=True)
    v = ProductVariantFactory()  # no price
    with pytest.raises(ValueError):
        compute_totals([(v, 1)], ng)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/checkout/tests/test_totals.py -v`
Expected: FAIL (`ModuleNotFoundError: apps.checkout.services.totals`).

- [ ] **Step 3: Implement compute_totals**

Create `backend/apps/checkout/services/totals.py`:

```python
"""compute_totals — the ONLY place order money is calculated. Used by cart display,
checkout, and order creation, so they can never disagree. Re-resolves every line via
resolve_price (snapshots are display-only). Rounds half-up per line, then sums."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from apps.pricing.services import resolve_price

CENT = Decimal("0.01")


def q2(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    discount: Decimal
    delivery: Decimal
    tax: Decimal
    grand_total: Decimal
    currency: str


def _coupon_discount(coupon, subtotal: Decimal) -> Decimal:
    """Discount amount on the subtotal. free_shipping discounts nothing here (it
    zeroes delivery instead). Never exceeds the subtotal."""
    if coupon is None or coupon.type == "free_shipping":
        return Decimal("0.00")
    if coupon.type == "percent":
        raw = subtotal * (coupon.value / Decimal("100"))
    else:  # fixed
        raw = coupon.value
    return min(q2(raw), subtotal)


def compute_totals(items, country, delivery_amount=Decimal("0.00"), coupon=None) -> Totals:
    """items = iterable of (ProductVariant, qty). delivery_amount already resolved by
    the caller (via apps.delivery). coupon must be pre-validated (validate_coupon)."""
    rate = country.tax_rate_percent / Decimal("100")
    subtotal = Decimal("0.00")
    for variant, qty in items:
        resolved = resolve_price(variant, country)
        if resolved is None:
            raise ValueError(f"Variant {variant.sku} has no price in {country.code}")
        subtotal += q2(resolved.amount) * qty
    subtotal = q2(subtotal)

    discount = _coupon_discount(coupon, subtotal)

    delivery = q2(delivery_amount)
    if coupon is not None and coupon.type == "free_shipping":
        delivery = Decimal("0.00")

    taxable = subtotal - discount
    if country.prices_include_tax:
        # Tax is the portion already inside the price: taxable - taxable/(1+r).
        tax = q2(taxable - (taxable / (Decimal("1") + rate))) if rate else Decimal("0.00")
        grand_total = q2(taxable + delivery)
    else:
        tax = q2(taxable * rate)
        grand_total = q2(taxable + tax + delivery)

    return Totals(
        subtotal=subtotal,
        discount=discount,
        delivery=delivery,
        tax=tax,
        grand_total=grand_total,
        currency=country.currency.code,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest apps/checkout/tests/test_totals.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add apps/checkout/services/totals.py apps/checkout/tests/test_totals.py
git commit -m "feat(checkout): compute_totals (per-line half-up, incl/excl tax, coupons, delivery)"
```

---

## Task 4: Docs + green sweep

- [ ] **Step 1: Document in architecture.md**

Add "Coupons & Totals (Plan-08c)": the `compute_totals` order of operations, inclusive-vs-exclusive tax rule, per-line rounding, the coupon error-code list, and the two documented simplifications (`applies_to` as an eligibility gate; `CouponRedemption.order_number` soft-ref + the last-use race note).

- [ ] **Step 2: Full suite + lint**

Run: `uv run python -m pytest` → all green.
Run: `uv run ruff check .` and `uv run python manage.py check` → clean.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: coupons & totals (Plan-08c) architecture notes"
```

---

## Self-Review checklist

- **Spec coverage:** Coupon model (all fields) ✓, CouponRedemption ✓ (soft order ref), validation with specific error codes ✓, compute_totals with inclusive/exclusive tax + per-line half-up rounding ✓, free_shipping ✓, delivery leg ✓.
- **Deviations (Fable-approved, documented):** `compute_totals(items, country, delivery_amount, coupon)` (no delivery_option/address — decouples from 08b); `CouponRedemption.order_number` soft-ref (decouples from 08d's Order); `applies_to` as eligibility gate (MVP).
- **Type consistency:** `validate_coupon(code, subtotal, country, user, email, item_product_ids, item_category_ids) -> CouponValidation(ok, error_code, coupon)`; `compute_totals(items, country, delivery_amount, coupon) -> Totals(subtotal, discount, delivery, tax, grand_total, currency)`; `q2()` helper — consistent across tasks and reused by 08d.
- **Placeholder scan:** none — full code in every code step.
- **Known race (documented, not a bug):** last-use coupon under concurrency; ledger records truth, tighten post-launch.
