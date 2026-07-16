# Plan-08d — Checkout Orchestration + Orders/Payments Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Runs on PostgreSQL (order-number sequence + `select_for_update`). Run tests with `uv run python -m pytest` from `backend/`.

**Goal:** The authenticated checkout endpoint that turns a cart into a `pending_payment` Order with reserved stock and an `initiated` Payment, plus Buy Now, per-country payment methods, and the reservation-expiry beat task. Introduces the `orders` and `payments` apps (models filed here per the approved boundary change) with **bank transfer** as the first working gateway.

**Architecture (per Fable 5 consult + Hammed's decision):**
- **Models filed forward.** `Order`/`OrderItem` (full Plan-10 field list) and `Payment`/`CountryPaymentGateway` (Plan-09 spec) land here, verbatim, so checkout has real tables to write. Plan-09/10 then add only *new* tables (`Refund`, `WebhookEvent`, `OrderEvent`) — the money tables stay append-only.
- **Two-phase checkout.** Phase 1 (one DB transaction): lock cart → validate → reserve stock → create Order + snapshot items → create Payment(initiated) → convert cart. Commit. Phase 2 (outside any transaction/lock): `gateway.initiate()` → store `gateway_reference`. **No external HTTP is ever held inside a DB lock.** For bank transfer `initiate()` is local, but the shape is built now so Plan-09's networked gateways drop in cleanly.
- **Attempt-suffixed reservation references** (`Order.reservation_reference`, e.g. `TC-100042` then `TC-100042/2`). This is load-bearing: `inventory.reserve()` is idempotent by reference, so re-reserving after an expiry-release under the *same* reference would silently reserve nothing. Commit/release always use `order.reservation_reference`. 08d writes attempt 1; Plan-09's late-payment path bumps it.
- **Order row is the single serialization point.** Every status change (`place_order`, `expire_pending_orders`, later `mark_paid`) locks the Order and re-checks status under the lock, so expiry-vs-payment races resolve deterministically.
- **Idempotency-Key**: Redis record (24h) is the fast path; `Payment.idempotency_key` UNIQUE is the durable backstop that survives Redis eviction. Same key + same payload → replay stored response; same key + different payload → 422.

**Tech Stack:** Django 5.2, DRF, PostgreSQL, Redis (idempotency + cache), Celery (beat). No new dependencies.

> **Part of the Plan-08 split:** 08a carts ∥ 08b delivery ∥ 08c coupons+totals → **08d checkout**. Depends on all three.
>
> **Deferred:** to **Plan-09** — Paystack/Flutterwave/Stripe/PayPal gateways, webhooks, `verify()`, refunds, and the *full* `mark_paid` with amount/currency equality checks (08d ships a minimal `mark_paid` used by tests + the bank-transfer manual-confirm path). To **Plan-10** — `OrderEvent` + `state.py` state machine (08d sets `order.status` directly in exactly two places, both refactored through `transition()` later), emails, invoices, customer/admin order APIs.

---

## Conventions

- New apps `apps.orders`, `apps.payments`. Add both to `INSTALLED_APPS` after `apps.checkout`.
- All checkout money comes from `apps.checkout.services.totals.compute_totals` — never the client, never a cart snapshot.
- Reservations use `apps.inventory.services.reserve/release/commit_sale` with `reference=order.reservation_reference`.
- `RESERVATION_TTL_MINUTES = 30` in settings; the expiry beat task runs every 5 min.

## File Structure

**Created:**
- `backend/apps/orders/__init__.py`, `apps.py`, `models.py`, `numbers.py`, `factories.py`, `migrations/__init__.py`, `0001_initial.py`, `0002_order_number_sequence.py`
- `backend/apps/payments/__init__.py`, `apps.py`, `models.py`, `services.py`, `factories.py`, `gateways/__init__.py`, `gateways/base.py`, `gateways/bank_transfer.py`, `gateways/registry.py`, `migrations/__init__.py`, `0001_initial.py`, `0002_seed_country_gateways.py`
- `backend/apps/checkout/services/idempotency.py`, `backend/apps/checkout/services/checkout.py`
- `backend/apps/checkout/views.py`, `backend/apps/checkout/urls.py`
- `backend/apps/checkout/tasks.py`
- Tests: `apps/orders/tests/`, `apps/payments/tests/`, `apps/checkout/tests/test_checkout_flow.py`, `test_idempotency.py`, `test_expiry.py`, `test_buy_now.py`, `test_payment_methods.py`

**Modified:**
- `backend/config/settings/base.py` (INSTALLED_APPS, `RESERVATION_TTL_MINUTES`, beat schedule), `backend/config/urls.py`, `docs/architecture.md`

---

## Task 1: Orders app — Order + OrderItem models + number sequence

**Files:**
- Create: `backend/apps/orders/{__init__.py,apps.py,models.py,numbers.py,factories.py}`, migrations
- Modify: `backend/config/settings/base.py`
- Test: `backend/apps/orders/tests/{__init__.py,test_models.py}`

- [ ] **Step 1: App config + register**

Create `backend/apps/orders/apps.py`:

```python
from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
```

Add `"apps.orders",` to `INSTALLED_APPS` (after `"apps.checkout",`).

- [ ] **Step 2: Write the models (full Plan-10 field list + reservation_reference)**

Create `backend/apps/orders/models.py`:

```python
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class Order(TimeStampedModel):
    number = models.CharField(max_length=20, unique=True)  # "TC-100001" or a legacy number
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="orders"
    )  # null ONLY for migrated guest orders / deleted accounts (Decision 7)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    country = models.ForeignKey("core.Country", on_delete=models.PROTECT)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=24, default="pending_payment")
    # pending_payment → processing → shipped → delivered → completed
    # + cancelled, expired, refunded, partially_refunded, needs_review, on_hold(migrated)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    coupon = models.ForeignKey("checkout.Coupon", null=True, blank=True, on_delete=models.SET_NULL)
    delivery_option_name = models.CharField(max_length=100, blank=True)
    shipping_address = models.JSONField(default=dict)  # snapshot, not FK
    billing_address = models.JSONField(default=dict)
    customer_note = models.TextField(blank=True)
    admin_note = models.TextField(blank=True)
    tracking_carrier = models.CharField(max_length=50, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)

    reservation_expires_at = models.DateTimeField(null=True, blank=True)
    # Attempt-suffixed reservation ledger key (starts == number; "/2" on re-reserve).
    reservation_reference = models.CharField(max_length=24, blank=True)

    source = models.CharField(max_length=20, default="web")  # web|legacy_ng|legacy_intl|admin
    legacy_number = models.CharField(max_length=20, blank=True, db_index=True)
    placed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-placed_at"]

    def __str__(self) -> str:
        return self.number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "catalog.ProductVariant", null=True, on_delete=models.SET_NULL
    )  # product may be deleted later — snapshots survive
    product_name = models.CharField(max_length=255)
    variant_name = models.CharField(max_length=255, blank=True)
    sku = models.CharField(max_length=64, blank=True)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()
    image_url = models.URLField(blank=True)
    # {"UK Warehouse": 3, "Lagos HQ": 2} — written by inventory.commit_sale via mark_paid.
    fulfillment_warehouses = models.JSONField(default=dict)

    def __str__(self) -> str:
        return f"{self.quantity}× {self.product_name} ({self.order_id})"
```

- [ ] **Step 3: Order-number generator (Postgres sequence)**

Create `backend/apps/orders/numbers.py`:

```python
"""TC-<seq> order numbers from a dedicated Postgres sequence starting at 100001.
A DB sequence (not max()+1) is gap-tolerant and concurrency-safe — two checkouts
never collide, and a rolled-back order simply burns a number (acceptable)."""
from django.db import connection

SEQUENCE_NAME = "order_number_seq"


def next_order_number() -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT nextval(%s)", [SEQUENCE_NAME])
        seq = cur.fetchone()[0]
    return f"TC-{seq}"
```

- [ ] **Step 4: Migrations — models, then the sequence**

Run: `uv run python manage.py makemigrations orders`
Expected: `0001_initial.py`.

Create `backend/apps/orders/migrations/0002_order_number_sequence.py`:

```python
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS order_number_seq START WITH 100001;",
            reverse_sql="DROP SEQUENCE IF EXISTS order_number_seq;",
        )
    ]
```

Run: `uv run python manage.py migrate orders`
Expected: OK.

- [ ] **Step 5: Factory**

Create `backend/apps/orders/factories.py`:

```python
import factory

from apps.orders.models import Order


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    email = factory.Sequence(lambda n: f"buyer{n}@x.com")
    status = "pending_payment"
    # number / country / currency / reservation_reference supplied by the test.
```

- [ ] **Step 6: Test the number generator + model**

Create `backend/apps/orders/tests/__init__.py` (empty) and `test_models.py`:

```python
import pytest

from apps.orders.numbers import next_order_number

pytestmark = pytest.mark.django_db


def test_order_numbers_increment_from_100001():
    n1 = next_order_number()
    n2 = next_order_number()
    assert n1.startswith("TC-")
    assert int(n2.split("-")[1]) == int(n1.split("-")[1]) + 1
```

Run: `uv run python -m pytest apps/orders/tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/orders config/settings/base.py
git commit -m "feat(orders): Order + OrderItem models + TC-<seq> number sequence"
```

---

## Task 2: Payments app — Payment + CountryPaymentGateway + seed

**Files:**
- Create: `backend/apps/payments/{__init__.py,apps.py,models.py,factories.py}`, migrations
- Modify: `backend/config/settings/base.py`
- Test: `backend/apps/payments/tests/{__init__.py,test_models.py}`

- [ ] **Step 1: App config + register**

Create `backend/apps/payments/apps.py`:

```python
from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
```

Add `"apps.payments",` to `INSTALLED_APPS` (after `"apps.orders",`).

- [ ] **Step 2: Write the models**

Create `backend/apps/payments/models.py`:

```python
from django.db import models


class Payment(models.Model):
    STATUSES = [
        ("initiated", "Initiated"), ("pending", "Pending"), ("succeeded", "Succeeded"),
        ("failed", "Failed"), ("cancelled", "Cancelled"),
        ("refunded", "Refunded"), ("partially_refunded", "Partially refunded"),
    ]

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payments")
    gateway = models.CharField(max_length=20)  # paystack|flutterwave|stripe|paypal|bank_transfer
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default="initiated", choices=STATUSES)
    gateway_reference = models.CharField(max_length=128, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=64, unique=True)
    raw_response = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.gateway} {self.amount} ({self.status}) for {self.order_id}"


class CountryPaymentGateway(models.Model):
    """Which gateways are offered per country — admin-managed data, not config."""

    country = models.ForeignKey("core.Country", on_delete=models.CASCADE)
    gateway = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = [("country", "gateway")]
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return f"{self.country_id}:{self.gateway} ({'on' if self.is_active else 'off'})"
```

- [ ] **Step 3: Migrate models**

Run: `uv run python manage.py makemigrations payments`
Run: `uv run python manage.py migrate payments`
Expected: OK.

- [ ] **Step 4: Seed per-country gateways**

Create `backend/apps/payments/migrations/0002_seed_country_gateways.py`:

```python
from django.db import migrations

SEED = {
    "NG": [("paystack", 1), ("flutterwave", 2), ("bank_transfer", 3)],
    "GB": [("stripe", 1), ("paypal", 2)],
    "US": [("stripe", 1), ("paypal", 2)],
    "CA": [("stripe", 1), ("paypal", 2)],
    "ZZ": [("stripe", 1), ("paypal", 2)],
}


def seed(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    CPG = apps.get_model("payments", "CountryPaymentGateway")
    for code, gateways in SEED.items():
        country = Country.objects.filter(code=code).first()
        if not country:
            continue
        for gateway, sort in gateways:
            CPG.objects.get_or_create(
                country=country, gateway=gateway,
                defaults={"is_active": True, "sort_order": sort},
            )


def unseed(apps, schema_editor):
    apps.get_model("payments", "CountryPaymentGateway").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("payments", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
```

Run: `uv run python manage.py migrate payments`

- [ ] **Step 5: Factory + model test**

Create `backend/apps/payments/factories.py`:

```python
import factory

from apps.payments.models import Payment


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment

    gateway = "bank_transfer"
    amount = "1000.00"
    status = "initiated"
    idempotency_key = factory.Sequence(lambda n: f"idem-{n}")
    # order / currency supplied by the test.
```

Create `backend/apps/payments/tests/__init__.py` (empty) and `test_models.py`:

```python
import pytest
from django.db import IntegrityError

from apps.payments.factories import PaymentFactory
from apps.orders.factories import OrderFactory
from apps.core.models import Country, Currency

pytestmark = pytest.mark.django_db


def _order():
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    ng = Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)
    return OrderFactory(number="TC-100001", country=ng, currency=ngn, reservation_reference="TC-100001")


def test_payment_idempotency_key_unique():
    order = _order()
    PaymentFactory(order=order, currency=order.currency, idempotency_key="dup")
    with pytest.raises(IntegrityError):
        PaymentFactory(order=order, currency=order.currency, idempotency_key="dup")
```

Run: `uv run python -m pytest apps/payments/tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/payments config/settings/base.py
git commit -m "feat(payments): Payment + CountryPaymentGateway models + per-country seed"
```

---

## Task 3: Gateway interface + bank_transfer + payment-methods endpoint

**Files:**
- Create: `backend/apps/payments/gateways/{__init__.py,base.py,bank_transfer.py,registry.py}`
- Create (checkout wiring): `backend/apps/checkout/views.py`, `urls.py` (payment-methods view)
- Modify: `backend/config/urls.py`
- Test: `backend/apps/payments/tests/test_bank_transfer.py`, `backend/apps/checkout/tests/test_payment_methods.py`

- [ ] **Step 1: Interface + result type**

Create `backend/apps/payments/gateways/__init__.py` (empty) and `base.py`:

```python
"""Payment gateway contract. Plan-08 ships bank_transfer; Plan-09 adds the four
networked gateways behind this same ABC (interface proven before the hard ones)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class InitiateResult:
    # action tells the storefront what to do: "bank_details" | "redirect" | "client_secret"
    action: str
    reference: str = ""
    data: dict = field(default_factory=dict)  # redirect_url / client_secret / bank details


class PaymentGateway(ABC):
    code: str
    supported_currencies: set[str]

    @abstractmethod
    def initiate(self, payment, order, return_url: str = "") -> InitiateResult: ...

    def verify(self, payment):  # overridden in Plan-09 (networked gateways)
        raise NotImplementedError

    def refund(self, payment, amount, reason):  # Plan-09
        raise NotImplementedError

    def parse_webhook(self, request):  # Plan-09
        raise NotImplementedError
```

- [ ] **Step 2: bank_transfer gateway**

Create `backend/apps/payments/gateways/bank_transfer.py`:

```python
from apps.core.models import SiteSetting
from apps.payments.gateways.base import InitiateResult, PaymentGateway


class BankTransferGateway(PaymentGateway):
    """Manual bank transfer (large in NG). No external HTTP — initiate() returns the
    merchant's bank details from SiteSetting; the order sits pending_payment until an
    admin confirms receipt (Plan-18) or a Paystack dedicated account webhook lands
    (Plan-09). Payment stays 'initiated'."""

    code = "bank_transfer"
    supported_currencies = {"NGN"}

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        return InitiateResult(
            action="bank_details",
            reference=order.number,
            data={
                "bank_name": SiteSetting.get_typed("bank_transfer.bank_name", ""),
                "account_name": SiteSetting.get_typed("bank_transfer.account_name", ""),
                "account_number": SiteSetting.get_typed("bank_transfer.account_number", ""),
                "amount": str(order.grand_total),
                "currency": order.currency_id,
                "reference": order.number,
                "instructions": "Use your order number as the transfer reference.",
            },
        )
```

- [ ] **Step 3: Gateway registry**

Create `backend/apps/payments/gateways/registry.py`:

```python
"""Maps a gateway code → instance. Plan-09 registers paystack/flutterwave/stripe/paypal."""
from apps.payments.gateways.bank_transfer import BankTransferGateway

_REGISTRY = {
    BankTransferGateway.code: BankTransferGateway(),
}


class UnknownGateway(Exception):
    pass


def get_gateway(code: str):
    try:
        return _REGISTRY[code]
    except KeyError as exc:
        raise UnknownGateway(code) from exc


def active_gateways_for(country) -> list[dict]:
    """Active CountryPaymentGateway rows for a country, in sort order."""
    from apps.payments.models import CountryPaymentGateway

    rows = CountryPaymentGateway.objects.filter(country=country, is_active=True).order_by(
        "sort_order"
    )
    return [{"gateway": r.gateway, "sort_order": r.sort_order} for r in rows]
```

- [ ] **Step 4: bank_transfer test**

Create `backend/apps/payments/tests/test_bank_transfer.py`:

```python
import pytest

from apps.core.models import Country, Currency, SiteSetting
from apps.orders.factories import OrderFactory
from apps.payments.factories import PaymentFactory
from apps.payments.gateways.registry import get_gateway

pytestmark = pytest.mark.django_db


def test_bank_transfer_initiate_returns_details():
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    ng = Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)
    SiteSetting.objects.create(key="bank_transfer.account_number", value="0123456789")
    order = OrderFactory(number="TC-100001", country=ng, currency=ngn,
                         reservation_reference="TC-100001", grand_total="5000.00")
    payment = PaymentFactory(order=order, currency=ngn, gateway="bank_transfer")

    result = get_gateway("bank_transfer").initiate(payment, order)

    assert result.action == "bank_details"
    assert result.data["account_number"] == "0123456789"
    assert result.data["reference"] == "TC-100001"
```

Run: `uv run python -m pytest apps/payments/tests/test_bank_transfer.py -v` → PASS.

- [ ] **Step 5: payment-methods endpoint**

Create `backend/apps/checkout/views.py`:

```python
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.country_context import resolve_country
from apps.payments.gateways.registry import active_gateways_for


class PaymentMethodsView(APIView):
    """GET /api/v1/checkout/payment-methods/?country=NG — active gateways for a country."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        country = resolve_country(request.query_params.get("country") or request.headers.get("X-Country"))
        return Response(active_gateways_for(country))
```

Create `backend/apps/checkout/urls.py`:

```python
from django.urls import path

from apps.checkout.views import PaymentMethodsView

urlpatterns = [
    path("checkout/payment-methods/", PaymentMethodsView.as_view(), name="checkout-payment-methods"),
]
```

In `backend/config/urls.py`, add:

```python
    path("api/v1/", include("apps.checkout.urls")),
```

- [ ] **Step 6: payment-methods test**

Create `backend/apps/checkout/tests/test_payment_methods.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.core.models import Country, Currency
from apps.payments.models import CountryPaymentGateway

pytestmark = pytest.mark.django_db


def test_payment_methods_for_ng():
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    ng = Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)
    CountryPaymentGateway.objects.create(country=ng, gateway="paystack", sort_order=1)
    CountryPaymentGateway.objects.create(country=ng, gateway="bank_transfer", sort_order=3)
    CountryPaymentGateway.objects.create(country=ng, gateway="off", is_active=False, sort_order=9)

    r = APIClient().get("/api/v1/checkout/payment-methods/?country=NG")
    gateways = [row["gateway"] for row in r.data]
    assert gateways == ["paystack", "bank_transfer"]  # sorted; inactive excluded
```

Run: `uv run python -m pytest apps/checkout/tests/test_payment_methods.py -v` → PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/payments/gateways apps/checkout config/urls.py
git commit -m "feat(payments): gateway ABC + bank_transfer + per-country payment-methods API"
```

---

## Task 4: Minimal mark_paid service

**Files:**
- Create: `backend/apps/payments/services.py`
- Test: `backend/apps/payments/tests/test_mark_paid.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/payments/tests/test_mark_paid.py`:

```python
import pytest
from decimal import Decimal

from apps.catalog.factories import ProductVariantFactory
from apps.checkout.factories import CouponFactory
from apps.checkout.models import CouponRedemption
from apps.core.models import Country, Currency
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory
from apps.payments.services import mark_paid

pytestmark = pytest.mark.django_db


def _setup():
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    ng = Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    return ng, ngn, variant


def test_mark_paid_commits_stock_and_flags_processing():
    ng, ngn, variant = _setup()
    order = OrderFactory(number="TC-100001", country=ng, currency=ngn,
                         reservation_reference="TC-100001", grand_total="1000.00")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-100001")
    payment = PaymentFactory(order=order, currency=ngn, status="initiated")

    mark_paid(payment)

    order.refresh_from_db(); payment.refresh_from_db()
    assert payment.status == "succeeded"
    assert order.status == "processing"
    # stock committed: on-hand dropped 10 → 8, reserved back to 0.
    si = variant.stock_items.get()
    assert si.quantity == 8 and si.reserved == 0
    # fulfillment recorded on the item.
    assert OrderItem.objects.get(order=order).fulfillment_warehouses == {"Lagos HQ": 2}


def test_mark_paid_writes_coupon_redemption():
    ng, ngn, variant = _setup()
    coupon = CouponFactory(code="TEN", type="percent", value="10.00")
    order = OrderFactory(number="TC-100002", country=ng, currency=ngn,
                         reservation_reference="TC-100002", coupon=coupon,
                         email="c@x.com", grand_total="900.00")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    reserve(variant, 2, ng, reference="TC-100002")
    mark_paid(PaymentFactory(order=order, currency=ngn))

    assert CouponRedemption.objects.filter(coupon=coupon, order_number="TC-100002").exists()


def test_mark_paid_idempotent():
    ng, ngn, variant = _setup()
    order = OrderFactory(number="TC-100003", country=ng, currency=ngn,
                         reservation_reference="TC-100003", grand_total="500.00")
    OrderItem.objects.create(order=order, variant=variant, product_name="X",
                             unit_price="500.00", line_total="500.00", quantity=1)
    reserve(variant, 1, ng, reference="TC-100003")
    p = PaymentFactory(order=order, currency=ngn)
    mark_paid(p); mark_paid(p)  # second call must be a no-op
    si = variant.stock_items.get()
    assert si.quantity == 9  # committed once, not twice
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/payments/tests/test_mark_paid.py -v`
Expected: FAIL (`ModuleNotFoundError: apps.payments.services`).

- [ ] **Step 3: Implement minimal mark_paid**

Create `backend/apps/payments/services.py`:

```python
"""mark_paid — the single 'money confirmed' entry point. Plan-09 wraps this with
gateway.verify() + an amount/currency equality check before calling it; the signature
is the seam. Order-row lock + status re-check makes it idempotent and race-safe vs the
expiry task."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Sum

from apps.inventory.models import StockMovement
from apps.inventory.services import commit_sale


def _fulfillment_by_warehouse(reference: str) -> dict:
    """From the reservation ledger: {warehouse_name: qty} for this reference."""
    rows = (
        StockMovement.objects.filter(reference=reference, reason="reservation")
        .values("stock_item__warehouse__name")
        .annotate(qty=Sum("delta_reserved"))
    )
    return {r["stock_item__warehouse__name"]: r["qty"] for r in rows}


@transaction.atomic
def mark_paid(payment) -> None:
    from apps.orders.models import Order

    order = Order.objects.select_for_update().get(pk=payment.order_id)
    if order.status != "pending_payment":
        return  # already processed / expired — idempotent no-op

    commit_sale(reference=order.reservation_reference)

    fulfil = _fulfillment_by_warehouse(order.reservation_reference)
    if fulfil:
        for item in order.items.all():
            item.fulfillment_warehouses = fulfil
            item.save(update_fields=["fulfillment_warehouses"])

    if order.coupon_id:
        from apps.checkout.models import CouponRedemption

        CouponRedemption.objects.get_or_create(
            coupon_id=order.coupon_id, order_number=order.number,
            defaults={"user": order.user, "email": order.email},
        )

    payment.status = "succeeded"
    payment.save(update_fields=["status", "updated_at"])
    order.status = "processing"
    order.reservation_expires_at = None
    order.save(update_fields=["status", "reservation_expires_at", "updated_at"])
```

> Note: `_fulfillment_by_warehouse` maps each warehouse to that reference's total reserved. If a single order reserves the same variant across warehouses the dict is per-warehouse totals across all lines — acceptable for the packing view at MVP; Plan-10 can refine to per-line if needed.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest apps/payments/tests/test_mark_paid.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/payments/services.py apps/payments/tests/test_mark_paid.py
git commit -m "feat(payments): minimal mark_paid (commit stock, redemption, fulfillment) — idempotent"
```

---

## Task 5: Checkout delivery-options endpoint

**Files:**
- Modify: `backend/apps/checkout/views.py`, `urls.py`
- Test: `backend/apps/checkout/tests/test_delivery_options.py`

`GET /api/v1/checkout/delivery-options/?address_id=&cart_id=` (auth) → resolves the user's cart to `(variant, qty)` lines + subtotal, then calls 08b's `options_for_address`.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/checkout/tests/test_delivery_options.py`:

```python
import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Currency, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def test_delivery_options_for_users_address(django_user_model):
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    ng = Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ngn, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)

    user = django_user_model.objects.create_user(email="u@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=1, unit_price_snapshot="1000.00")

    client = APIClient(); client.force_authenticate(user)
    r = client.get(f"/api/v1/checkout/delivery-options/?address_id={addr.id}&cart_id={cart.id}",
                   HTTP_X_COUNTRY="NG")
    assert r.status_code == 200
    assert [o["name"] for o in r.data] == ["Lagos Flat"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/checkout/tests/test_delivery_options.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Implement**

Add to `backend/apps/checkout/views.py`:

```python
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.accounts.models import Address
from apps.carts.models import Cart
from apps.checkout.services.totals import compute_totals
from apps.delivery.services import options_for_address


def _cart_lines(cart):
    """[(variant, qty)] for a cart, prefetching variants."""
    return [(i.variant, i.quantity) for i in cart.items.select_related("variant").all()]


class DeliveryOptionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        address = get_object_or_404(Address, pk=request.query_params.get("address_id"), user=request.user)
        cart = get_object_or_404(Cart, pk=request.query_params.get("cart_id"), user=request.user, status="active")
        lines = _cart_lines(cart)
        if not lines:
            raise ValidationError("Cart is empty.")
        totals = compute_totals(lines, request.country)
        return Response(options_for_address(address, lines, totals.subtotal))
```

Add to `backend/apps/checkout/urls.py`:

```python
    path("checkout/delivery-options/", DeliveryOptionsView.as_view(), name="checkout-delivery-options"),
```

and import `DeliveryOptionsView`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest apps/checkout/tests/test_delivery_options.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/checkout
git commit -m "feat(checkout): delivery-options endpoint (cart → priced options for an address)"
```

---

## Task 6: Idempotency-Key store

**Files:**
- Create: `backend/apps/checkout/services/idempotency.py`
- Test: `backend/apps/checkout/tests/test_idempotency.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/checkout/tests/test_idempotency.py`:

```python
import pytest

from apps.checkout.services.idempotency import (
    IdempotencyConflict,
    IdempotencyKeyReused,
    begin,
    finish,
)

pytestmark = pytest.mark.django_db


def test_begin_then_finish_then_replay():
    ok = begin(user_id=1, key="abc", request_hash="h1")
    assert ok is None  # first call: proceed
    finish(user_id=1, key="abc", request_hash="h1", status_code=201, body={"order_number": "TC-100001"})
    replay = begin(user_id=1, key="abc", request_hash="h1")
    assert replay == (201, {"order_number": "TC-100001"})


def test_same_key_different_payload_rejected():
    begin(user_id=1, key="k2", request_hash="h1")
    finish(user_id=1, key="k2", request_hash="h1", status_code=201, body={"x": 1})
    with pytest.raises(IdempotencyKeyReused):
        begin(user_id=1, key="k2", request_hash="DIFFERENT")


def test_inflight_conflicts():
    begin(user_id=1, key="k3", request_hash="h1")  # marks in-progress, not finished
    with pytest.raises(IdempotencyConflict):
        begin(user_id=1, key="k3", request_hash="h1")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/checkout/tests/test_idempotency.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the two-phase store (Redis via Django cache)**

Create `backend/apps/checkout/services/idempotency.py`:

```python
"""Two-phase idempotency for POST /checkout/. Redis (Django cache) is the fast path;
the Payment.idempotency_key UNIQUE constraint is the durable backstop in the checkout
service. Record shape: {"status": "in_progress"|"done", "request_hash", "code", "body"}."""
from __future__ import annotations

import hashlib
import json

from django.core.cache import cache

INFLIGHT_TTL = 300      # 5 min — a stuck in-progress marker self-heals
DONE_TTL = 86400        # 24 h replay window (API convention)


class IdempotencyConflict(Exception):
    """A request with this key is still in progress."""


class IdempotencyKeyReused(Exception):
    """Same key, different request payload — a client bug; never execute."""


def _key(user_id, key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return f"idem:checkout:{user_id}:{digest}"


def hash_payload(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def begin(user_id, key: str, request_hash: str):
    """Reserve the key. Returns None to proceed, or (code, body) to replay.
    Raises IdempotencyConflict (in progress) or IdempotencyKeyReused (payload changed)."""
    cache_key = _key(user_id, key)
    placed = cache.add(
        cache_key, {"status": "in_progress", "request_hash": request_hash}, INFLIGHT_TTL
    )
    if placed:
        return None
    record = cache.get(cache_key)
    if record is None:  # expired between add() and get() — treat as fresh
        cache.set(cache_key, {"status": "in_progress", "request_hash": request_hash}, INFLIGHT_TTL)
        return None
    if record.get("request_hash") != request_hash:
        raise IdempotencyKeyReused()
    if record.get("status") == "done":
        return record["code"], record["body"]
    raise IdempotencyConflict()


def finish(user_id, key: str, request_hash: str, status_code: int, body: dict) -> None:
    cache.set(
        _key(user_id, key),
        {"status": "done", "request_hash": request_hash, "code": status_code, "body": body},
        DONE_TTL,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest apps/checkout/tests/test_idempotency.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/checkout/services/idempotency.py apps/checkout/tests/test_idempotency.py
git commit -m "feat(checkout): two-phase Idempotency-Key store (Redis fast path)"
```

---

## Task 7: The checkout orchestration service + endpoint

**Files:**
- Create: `backend/apps/checkout/services/checkout.py`
- Modify: `backend/apps/checkout/views.py`, `urls.py`, `backend/config/settings/base.py` (`RESERVATION_TTL_MINUTES`)
- Test: `backend/apps/checkout/tests/test_checkout_flow.py`

**Flow (`place_order`):**
1. Lock cart (`select_for_update`); must be `active` & non-empty & belong to user → else 409 `cart_not_active`.
2. Validate address & billing belong to user.
3. Re-validate each line: `sellable_in` + `resolve_price` (drift/removal → 409 `line_unavailable`).
4. Server-side re-match delivery option via 08b (`options_for_address`) — the chosen id must be in the fresh list → else 409 `delivery_option_invalid`; take its **server-computed price**.
5. Validate gateway active for country (`active_gateways_for`) → else 400 `gateway_unavailable`.
6. Validate coupon (if any) via 08c → 400 with error code.
7. `compute_totals(lines, country, delivery_amount, coupon)`. If `expected_total` supplied and ≠ grand_total → 409 `cart_changed` + fresh totals.
8. `number = next_order_number()`; reserve each line `reserve(variant, qty, country, reference=number)` (InsufficientStock → 409 `insufficient_stock` naming the SKU; whole txn rolls back).
9. Create `Order(status="pending_payment", reservation_reference=number, reservation_expires_at=now+TTL, ...snapshots...)` + `OrderItem`s.
10. Create `Payment(status="initiated", idempotency_key=key)`.
11. Convert cart (`status="converted"`).
Commit. **Then** (phase 2, no lock) `gateway.initiate()` → save `gateway_reference`/`raw_response`. Return `{order_number, payment:{gateway, action, data}}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/apps/checkout/tests/test_checkout_flow.py`:

```python
import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from apps.accounts.models import Address
from apps.carts.factories import CartFactory
from apps.carts.models import Cart, CartItem
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Currency, Region
from apps.delivery.factories import DeliveryOptionFactory
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.models import StockMovement
from apps.orders.models import Order, OrderItem
from apps.payments.models import CountryPaymentGateway, Payment
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def _world(stock=10):
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    ng = Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True,
                                tax_rate_percent=Decimal("7.5"), prices_include_tax=True)
    wh = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    wh.serves_countries.add(ng)
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    opt = DeliveryOptionFactory(currency=ngn, name="Lagos Flat", price="1500.00")
    opt.regions.add(lagos)
    CountryPaymentGateway.objects.create(country=ng, gateway="bank_transfer", sort_order=1)
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=stock)
    return ng, ngn, variant, lagos, opt


def _user_cart(user, ng, ngn, variant, qty=2):
    cart = CartFactory(user=user, country=ng, currency=ngn)
    CartItem.objects.create(cart=cart, variant=variant, quantity=qty, unit_price_snapshot="1000.00")
    return cart


def _checkout_body(cart, addr, opt):
    return {
        "cart_id": str(cart.id), "address_id": addr.id,
        "delivery_option_id": opt.id, "payment_gateway": "bank_transfer",
    }


def test_checkout_happy_path_creates_order_and_reservation(django_user_model):
    ng, ngn, variant, lagos, opt = _world(stock=10)
    user = django_user_model.objects.create_user(email="u@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant, qty=2)

    client = APIClient(); client.force_authenticate(user)
    r = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json",
                    HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="key-1")

    assert r.status_code == 201, r.data
    order = Order.objects.get(number=r.data["order_number"])
    assert order.status == "pending_payment"
    assert order.user == user
    # 2000 subtotal (incl tax) + 1500 delivery = 3500 grand.
    assert order.grand_total == Decimal("3500.00")
    assert order.reservation_reference == order.number
    assert order.reservation_expires_at is not None
    assert OrderItem.objects.filter(order=order).count() == 1
    # stock reserved, cart converted, payment initiated, bank details returned.
    assert variant.stock_items.get().reserved == 2
    assert Cart.objects.get(id=cart.id).status == "converted"
    assert Payment.objects.get(order=order).status == "initiated"
    assert r.data["payment"]["action"] == "bank_details"


def test_idempotent_replay_returns_same_order_without_double_reserving(django_user_model):
    ng, ngn, variant, lagos, opt = _world(stock=10)
    user = django_user_model.objects.create_user(email="u2@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant, qty=2)
    client = APIClient(); client.force_authenticate(user)

    r1 = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json",
                     HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="same")
    r2 = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json",
                     HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="same")
    assert r1.data["order_number"] == r2.data["order_number"]
    assert Order.objects.count() == 1
    assert variant.stock_items.get().reserved == 2  # not 4


def test_insufficient_stock_rolls_back_everything(django_user_model):
    ng, ngn, variant, lagos, opt = _world(stock=1)  # only 1 in stock
    user = django_user_model.objects.create_user(email="u3@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant, qty=2)  # wants 2
    client = APIClient(); client.force_authenticate(user)

    # Bypass the cart stock-cap by writing the line directly (already done above via qty=2
    # vs stock=1). Force the row to 2 in case add_item capped it:
    CartItem.objects.filter(cart=cart).update(quantity=2)

    r = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json",
                    HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="k")
    assert r.status_code == 409
    assert Order.objects.count() == 0
    assert Payment.objects.count() == 0
    assert StockMovement.objects.count() == 0  # nothing reserved
    assert variant.stock_items.get().reserved == 0
    assert Cart.objects.get(id=cart.id).status == "active"  # not converted


def test_missing_idempotency_key_is_400(django_user_model):
    ng, ngn, variant, lagos, opt = _world()
    user = django_user_model.objects.create_user(email="u4@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant)
    client = APIClient(); client.force_authenticate(user)
    r = client.post("/api/v1/checkout/", _checkout_body(cart, addr, opt), format="json", HTTP_X_COUNTRY="NG")
    assert r.status_code == 400


def test_expected_total_mismatch_returns_409(django_user_model):
    ng, ngn, variant, lagos, opt = _world()
    user = django_user_model.objects.create_user(email="u5@x.com", password="pw")
    addr = Address.objects.create(user=user, line1="1 St", country_code="NG", state_region=lagos)
    cart = _user_cart(user, ng, ngn, variant)
    body = _checkout_body(cart, addr, opt); body["expected_total"] = "1.00"
    client = APIClient(); client.force_authenticate(user)
    r = client.post("/api/v1/checkout/", body, format="json", HTTP_X_COUNTRY="NG", HTTP_IDEMPOTENCY_KEY="k")
    assert r.status_code == 409
    assert r.data["error"] == "cart_changed"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/checkout/tests/test_checkout_flow.py -v`
Expected: FAIL (404 / import errors).

- [ ] **Step 3: Settings**

In `backend/config/settings/base.py`, add near the other domain constants:

```python
RESERVATION_TTL_MINUTES = env.int("RESERVATION_TTL_MINUTES", default=30)
```

- [ ] **Step 4: Implement the orchestration service**

Create `backend/apps/checkout/services/checkout.py`:

```python
"""Checkout orchestration. Two-phase: everything money/stock happens in ONE DB txn
(phase 1); the external gateway call happens AFTER commit (phase 2) so no HTTP is ever
held under a DB lock. Raises CheckoutError(code, detail, extra) which the view maps to
409/400. All money comes from compute_totals; delivery price is re-derived server-side."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Address
from apps.carts.models import Cart
from apps.catalog.services import sellable_in
from apps.checkout.services.coupons import validate_coupon
from apps.checkout.services.totals import compute_totals
from apps.delivery.services import options_for_address
from apps.inventory.services import InsufficientStock, reserve
from apps.orders.models import Order, OrderItem
from apps.orders.numbers import next_order_number
from apps.payments.gateways.registry import active_gateways_for, get_gateway
from apps.payments.models import Payment


class CheckoutError(Exception):
    def __init__(self, code: str, detail: str = "", extra: dict | None = None, http: int = 409):
        self.code = code
        self.detail = detail or code
        self.extra = extra or {}
        self.http = http
        super().__init__(self.detail)


@dataclass
class CheckoutResult:
    order: Order
    payment: Payment


def _address_snapshot(addr: Address) -> dict:
    return {
        "first_name": addr.first_name, "last_name": addr.last_name, "phone": addr.phone,
        "line1": addr.line1, "line2": addr.line2, "country_code": addr.country_code,
        "state": addr.state_region.name if addr.state_region else addr.state_text,
        "area": addr.area_region.name if addr.area_region else addr.city_text,
        "postcode": addr.postcode,
    }


def place_order(*, user, country, key: str, cart_id, address_id, delivery_option_id,
                payment_gateway: str, billing_address_id=None, coupon_code: str = "",
                notes: str = "", expected_total=None) -> CheckoutResult:
    # Durable backstop: a completed payment already exists for this key → replay it.
    existing = Payment.objects.filter(idempotency_key=key, order__user=user).select_related("order").first()
    if existing:
        return CheckoutResult(order=existing.order, payment=existing)

    with transaction.atomic():
        cart = Cart.objects.select_for_update().filter(pk=cart_id, user=user).first()
        if cart is None or cart.status != "active":
            raise CheckoutError("cart_not_active", "Cart is not active.")
        lines = [(i.variant, i.quantity) for i in cart.items.select_related("variant__product").all()]
        if not lines:
            raise CheckoutError("cart_empty", "Cart is empty.")

        address = Address.objects.filter(pk=address_id, user=user).first()
        if address is None:
            raise CheckoutError("address_invalid", "Address not found.", http=400)
        billing = address
        if billing_address_id:
            billing = Address.objects.filter(pk=billing_address_id, user=user).first() or address

        # Re-validate every line against live catalog + pricing.
        for variant, qty in lines:
            if not sellable_in(variant.product, country):
                raise CheckoutError("line_unavailable", f"{variant.sku} is not available.",
                                    extra={"sku": variant.sku})

        # Server-side delivery re-match — never trust the client's option list.
        subtotal_preview = compute_totals(lines, country).subtotal
        options = options_for_address(address, lines, subtotal_preview)
        chosen = next((o for o in options if o["id"] == delivery_option_id), None)
        if chosen is None:
            raise CheckoutError("delivery_option_invalid", "Delivery option not valid for this address.")

        # Gateway must be active for the country.
        if payment_gateway not in {g["gateway"] for g in active_gateways_for(country)}:
            raise CheckoutError("gateway_unavailable", "Payment method not available.", http=400)

        # Coupon (optional).
        coupon = None
        if coupon_code:
            product_ids = {v.product_id for v, _ in lines}
            result = validate_coupon(coupon_code, subtotal_preview, country, user=user,
                                     email=user.email, item_product_ids=product_ids)
            if not result.ok:
                raise CheckoutError(f"coupon_{result.error_code}", "Coupon not valid.", http=400)
            coupon = result.coupon

        from decimal import Decimal
        totals = compute_totals(lines, country, delivery_amount=Decimal(chosen["price"]), coupon=coupon)

        if expected_total is not None and Decimal(str(expected_total)) != totals.grand_total:
            raise CheckoutError("cart_changed", "Totals changed.",
                                extra={"totals": _totals_dict(totals)})

        number = next_order_number()
        try:
            for variant, qty in lines:
                reserve(variant, qty, country, reference=number)
        except InsufficientStock as exc:
            raise CheckoutError("insufficient_stock", str(exc)) from exc

        order = Order.objects.create(
            number=number, user=user, email=user.email, phone=user.phone,
            country=country, currency=country.currency, status="pending_payment",
            subtotal=totals.subtotal, discount_total=totals.discount,
            shipping_total=totals.delivery, tax_total=totals.tax, grand_total=totals.grand_total,
            coupon=coupon, delivery_option_name=chosen["name"],
            shipping_address=_address_snapshot(address), billing_address=_address_snapshot(billing),
            customer_note=notes, reservation_reference=number,
            reservation_expires_at=timezone.now() + timedelta(minutes=settings.RESERVATION_TTL_MINUTES),
        )
        for variant, qty in lines:
            resolved_unit = next(o for o in [totals] if o)  # unit from line re-price
            from apps.pricing.services import resolve_price
            rp = resolve_price(variant, country)
            OrderItem.objects.create(
                order=order, variant=variant, product_name=variant.product.name,
                variant_name=", ".join(f"{k}: {v}" for k, v in (variant.option_values or {}).items()),
                sku=variant.sku, unit_price=rp.amount, line_total=(rp.amount * qty), quantity=qty,
            )
        payment = Payment.objects.create(
            order=order, gateway=payment_gateway, amount=totals.grand_total,
            currency=country.currency, status="initiated", idempotency_key=key,
        )
        cart.status = "converted"
        cart.save(update_fields=["status", "updated_at"])

    # Phase 2 — external call AFTER commit, no lock held.
    init = get_gateway(payment_gateway).initiate(payment, order)
    payment.gateway_reference = init.reference
    payment.raw_response = init.data
    payment.save(update_fields=["gateway_reference", "raw_response", "updated_at"])
    order._initiate = init  # stash for the view's response
    return CheckoutResult(order=order, payment=payment)


def _totals_dict(t) -> dict:
    return {
        "subtotal": str(t.subtotal), "discount": str(t.discount), "delivery": str(t.delivery),
        "tax": str(t.tax), "grand_total": str(t.grand_total), "currency": t.currency,
    }
```

> Clean-up note for the executor: the `resolved_unit = next(...)` line is a leftover — delete it; the loop uses `resolve_price(variant, country)` directly. (Left visible so you SEE it and remove it; do not ship it.)

- [ ] **Step 5: Implement the view + url**

Add to `backend/apps/checkout/views.py`:

```python
from rest_framework import status

from apps.checkout.services.checkout import CheckoutError, place_order
from apps.checkout.services.idempotency import (
    IdempotencyConflict,
    IdempotencyKeyReused,
    begin,
    finish,
    hash_payload,
)


class CheckoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        key = request.headers.get("Idempotency-Key")
        if not key:
            return Response({"error": "idempotency_key_required"}, status=status.HTTP_400_BAD_REQUEST)

        payload = {
            "cart_id": str(request.data.get("cart_id")),
            "address_id": request.data.get("address_id"),
            "billing_address_id": request.data.get("billing_address_id"),
            "delivery_option_id": request.data.get("delivery_option_id"),
            "coupon_code": request.data.get("coupon_code", ""),
            "payment_gateway": request.data.get("payment_gateway"),
        }
        request_hash = hash_payload(payload)
        try:
            replay = begin(request.user.id, key, request_hash)
        except IdempotencyKeyReused:
            return Response({"error": "idempotency_key_reused"}, status=422)
        except IdempotencyConflict:
            return Response({"error": "idempotency_in_progress"}, status=409, headers={"Retry-After": "2"})
        if replay is not None:
            return Response(replay[1], status=replay[0])

        try:
            result = place_order(
                user=request.user, country=request.country, key=key,
                cart_id=payload["cart_id"], address_id=payload["address_id"],
                billing_address_id=payload["billing_address_id"],
                delivery_option_id=payload["delivery_option_id"],
                payment_gateway=payload["payment_gateway"],
                coupon_code=payload["coupon_code"],
                notes=request.data.get("notes", ""),
                expected_total=request.data.get("expected_total"),
            )
        except CheckoutError as exc:
            body = {"error": exc.code, "detail": exc.detail, **exc.extra}
            return Response(body, status=exc.http)

        init = getattr(result.order, "_initiate", None)
        body = {
            "order_number": result.order.number,
            "payment": {
                "gateway": result.payment.gateway,
                "action": init.action if init else "",
                "data": init.data if init else {},
            },
        }
        finish(request.user.id, key, request_hash, status.HTTP_201_CREATED, body)
        return Response(body, status=status.HTTP_201_CREATED)
```

Add to `backend/apps/checkout/urls.py`:

```python
    path("checkout/", CheckoutView.as_view(), name="checkout"),
```

and import `CheckoutView`.

- [ ] **Step 6: Run to verify it passes**

Run: `uv run python -m pytest apps/checkout/tests/test_checkout_flow.py -v`
Expected: PASS (5 tests). Remove the flagged leftover line if any test trips on it.

- [ ] **Step 7: Commit**

```bash
git add apps/checkout config/settings/base.py
git commit -m "feat(checkout): POST /checkout/ orchestration (reserve→order→payment, two-phase, idempotent)"
```

---

## Task 8: Buy Now (express cart)

**Files:**
- Modify: `backend/apps/checkout/views.py`, `urls.py`
- Test: `backend/apps/checkout/tests/test_buy_now.py`

`POST /api/v1/checkout/buy-now/` `{variant_id, quantity}` (auth) → upsert the user's single `kind="express"` cart with just that line, return the priced cart. The storefront then runs normal checkout against the express cart id, leaving the standard cart untouched.

- [ ] **Step 1: Write the failing test**

Create `backend/apps/checkout/tests/test_buy_now.py`:

```python
import pytest
from decimal import Decimal
from rest_framework.test import APIClient

from apps.carts.models import Cart
from apps.catalog.factories import ProductVariantFactory
from apps.core.models import Country, Currency
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.pricing.models import Price

pytestmark = pytest.mark.django_db


def test_buy_now_creates_single_express_cart(django_user_model):
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    ng = Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)
    wh = WarehouseFactory(location_country="NG", priority=1); wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    Price.objects.create(variant=variant, currency=ngn, amount=Decimal("1000.00"))
    StockItemFactory(variant=variant, warehouse=wh, quantity=5)
    user = django_user_model.objects.create_user(email="b@x.com", password="pw")
    client = APIClient(); client.force_authenticate(user)

    r1 = client.post("/api/v1/checkout/buy-now/", {"variant_id": variant.id, "quantity": 1},
                     format="json", HTTP_X_COUNTRY="NG")
    assert r1.status_code == 200
    assert r1.data["kind"] == "express"
    assert r1.data["items"][0]["quantity"] == 1

    # A second Buy Now replaces the express cart contents (still one express cart).
    r2 = client.post("/api/v1/checkout/buy-now/", {"variant_id": variant.id, "quantity": 3},
                     format="json", HTTP_X_COUNTRY="NG")
    assert r2.data["id"] == r1.data["id"]
    assert r2.data["items"][0]["quantity"] == 3
    assert Cart.objects.filter(user=user, kind="express", status="active").count() == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/checkout/tests/test_buy_now.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Implement**

Add to `backend/apps/checkout/views.py`:

```python
from apps.carts.models import CartItem
from apps.carts.serializers import serialize_cart
from apps.carts.services import get_or_create_cart, set_quantity
from apps.catalog.models import ProductVariant


class BuyNowView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        variant = get_object_or_404(ProductVariant, pk=request.data.get("variant_id"), is_active=True)
        qty = int(request.data.get("quantity", 1))
        cart = get_or_create_cart(request, kind="express")
        # Express cart holds exactly the Buy-Now item — clear then set.
        CartItem.objects.filter(cart=cart).delete()
        set_quantity(cart, variant, qty, request.country)
        return Response(serialize_cart(cart, request.country))
```

Add to `backend/apps/checkout/urls.py`:

```python
    path("checkout/buy-now/", BuyNowView.as_view(), name="checkout-buy-now"),
```

and import `BuyNowView`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest apps/checkout/tests/test_buy_now.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/checkout
git commit -m "feat(checkout): Buy Now express cart"
```

---

## Task 9: Reservation-expiry beat task

**Files:**
- Create: `backend/apps/checkout/tasks.py`
- Modify: `backend/config/settings/base.py` (beat schedule)
- Test: `backend/apps/checkout/tests/test_expiry.py`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/checkout/tests/test_expiry.py`:

```python
import pytest
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone

from apps.catalog.factories import ProductVariantFactory
from apps.checkout.tasks import expire_pending_orders
from apps.core.models import Country, Currency
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.inventory.services import reserve
from apps.orders.factories import OrderFactory
from apps.orders.models import Order

pytestmark = pytest.mark.django_db


def _reserved_order(number, expires_delta):
    ngn = Currency.objects.create(code="NGN", symbol="₦")
    ng = Country.objects.create(code="NG", name="Nigeria", currency=ngn, is_default=True)
    wh = WarehouseFactory(location_country="NG", priority=1); wh.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=wh, quantity=10)
    reserve(variant, 3, ng, reference=number)
    order = OrderFactory(number=number, country=ng, currency=ngn, status="pending_payment",
                         reservation_reference=number,
                         reservation_expires_at=timezone.now() + expires_delta)
    return order, variant


def test_past_due_pending_order_expires_and_releases_stock():
    order, variant = _reserved_order("TC-100001", -timedelta(minutes=1))
    assert variant.stock_items.get().reserved == 3

    n = expire_pending_orders()

    assert n == 1
    order.refresh_from_db()
    assert order.status == "expired"
    assert variant.stock_items.get().reserved == 0  # released


def test_not_yet_due_order_untouched():
    order, variant = _reserved_order("TC-100002", timedelta(minutes=10))
    assert expire_pending_orders() == 0
    order.refresh_from_db()
    assert order.status == "pending_payment"
    assert variant.stock_items.get().reserved == 3
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run python -m pytest apps/checkout/tests/test_expiry.py -v`
Expected: FAIL (`ModuleNotFoundError: apps.checkout.tasks`).

- [ ] **Step 3: Implement the task (per-order txn, locked status re-check)**

Create `backend/apps/checkout/tasks.py`:

```python
"""expire_pending_orders — release stock for pending orders past their reservation TTL.
One transaction PER ORDER (a poison order can't roll back its siblings), each locking
the Order and re-checking status under the lock so it can't race mark_paid. release() is
ledger-idempotent, so a double-run is safe."""
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from apps.inventory.services import release


@shared_task
def expire_pending_orders() -> int:
    from apps.orders.models import Order

    now = timezone.now()
    due_ids = list(
        Order.objects.filter(status="pending_payment", reservation_expires_at__lt=now)
        .values_list("pk", flat=True)
    )
    expired = 0
    for pk in due_ids:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=pk)
            if order.status != "pending_payment" or order.reservation_expires_at >= now:
                continue  # a payment landed first, or it's no longer due
            release(reference=order.reservation_reference)
            order.status = "expired"
            order.save(update_fields=["status", "updated_at"])
            expired += 1
    return expired
```

In `backend/config/settings/base.py`, add to `CELERY_BEAT_SCHEDULE`:

```python
    "expire-pending-orders": {
        "task": "apps.checkout.tasks.expire_pending_orders",
        "schedule": 300.0,  # every 5 min
    },
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run python -m pytest apps/checkout/tests/test_expiry.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apps/checkout/tasks.py config/settings/base.py
git commit -m "feat(checkout): expire_pending_orders beat task (per-order, locked, idempotent)"
```

---

## Task 10: Docs + full green sweep + checkpoint prep

- [ ] **Step 1: Document in architecture.md**

Add "Checkout & Orders/Payments scaffolding (Plan-08d)": the two-phase flow, attempt-suffixed `reservation_reference` and *why* (the reserve-after-release no-op trap), the Order-row-lock serialization rule, the idempotency two-phase + `Payment.idempotency_key` durable backstop, and the deferred seams to Plan-09/10 (Refund/WebhookEvent/OrderEvent, full mark_paid with verify()).

- [ ] **Step 2: Full backend suite + lint**

Run: `uv run python -m pytest`
Expected: all green (existing 103 + carts + delivery + coupons/totals + orders/payments/checkout).
Run: `uv run ruff check .` and `uv run python manage.py check`
Expected: clean.

- [ ] **Step 3: Seed bank details for the demo (SiteSetting)**

Via Django shell or a data step, set `bank_transfer.bank_name`, `bank_transfer.account_name`, `bank_transfer.account_number` SiteSettings so the checkpoint demo shows real bank details (use placeholder test values; Hammed supplies live ones later).

- [ ] **Step 4: Commit**

```bash
git add docs/architecture.md
git commit -m "docs: checkout + orders/payments scaffolding (Plan-08d) architecture notes"
```

- [ ] **Step 5: Live smoke for the checkpoint**

Against the running stack, via Swagger `/api/docs/` (or curl): create a 1-unit stock item → add to cart → `POST /checkout/` with a bank_transfer gateway → observe `pending_payment` order + `reserved=1` + bank details → run `expire_pending_orders` (or wait) → observe `expired` + `reserved=0`. Capture the output for Hammed.

---

## Self-Review checklist

- **Spec coverage:** authenticated `POST /checkout/` creating pending order + reservation ✓, `GET /checkout/delivery-options/` ✓, `GET /checkout/payment-methods/` ✓, Buy Now ✓, reservation TTL + `expire_pending_orders` ✓, Idempotency-Key ✓, server-side re-validation (address, delivery re-match, sellable, gateway) ✓.
- **Models filed forward (approved):** full `Order`/`OrderItem`/`Payment`/`CountryPaymentGateway` + `reservation_reference` ✓; bank_transfer working end-to-end ✓.
- **Fable guards implemented:** two-phase (HTTP outside lock) ✓, order-row-lock serialization ✓, attempt-suffixed reference column ✓ (attempt-2 bump is Plan-09's late-payment path — the column + commit/release-by-reference seam exists now), cart lock + convert-in-txn ✓, `expected_total` guard ✓, `Payment.idempotency_key` durable backstop ✓, per-order expiry txn with `skip_locked`-equivalent status re-check ✓, insufficient-stock full rollback (test asserts zero movements) ✓.
- **Type consistency:** `place_order(**kwargs) -> CheckoutResult(order, payment)`, `CheckoutError(code, detail, extra, http)`, `mark_paid(payment)`, `next_order_number()`, `get_gateway(code)`, `active_gateways_for(country)`, `begin/finish/hash_payload` — consistent across tasks.
- **Placeholder scan:** one deliberately-flagged leftover line in `place_order` (`resolved_unit = next(...)`) marked "delete it" so the executor sees and removes it; the loop already uses `resolve_price` directly. No other placeholders.
- **Deferred correctly:** OrderEvent/state.py, emails, invoices, order APIs (Plan-10); networked gateways, webhooks, verify(), refunds, attempt-2 re-reserve on late payment (Plan-09).

---

## Post-Plan-08 note for master-tokerebuild.md

After 08d lands, update the master guide's Plan-09 and Plan-10 sections to note that `Order`/`OrderItem`/`Payment`/`CountryPaymentGateway` **already exist** (built in 08d) — those stages add only `Refund`, `WebhookEvent`, `OrderEvent`, the networked gateways, and behavior (lifecycle, emails, invoices, refunds, webhooks). No re-creation of the money models.
