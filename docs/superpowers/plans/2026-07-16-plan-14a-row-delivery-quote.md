# Plan-14a — Rest-of-World delivery quote-after-payment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a real Rest-of-World customer check out, pay for goods by bank transfer, then be quoted freight afterwards — with the quote and the freight cash both recorded on the system.

**Architecture:** `options_for_address()` resolves the shipping address's country through the existing `resolve_country()` (unknown ISO code → the ZZ Rest-of-World row) and filters options to the order's currency. A `quote_required` delivery option carries no price at all (`price: None`). Placing an order on such an option creates a `ShippingQuote` row in `awaiting_quote`. The **quote** (an obligation, no money moved) lives on `ShippingQuote`; the **freight cash** is an ordinary `Payment` with `purpose="freight"`, so "how much money came in" stays one query against one table forever.

**Tech Stack:** Django 5 / DRF / Postgres / pytest / ruff. Backend only — `storefront/` is a bare scaffold and inherits a rendering contract for Plan-14.

**Spec:** `docs/superpowers/specs/2026-07-16-row-delivery-quote-design.md` — read it before Task 1. It records *why*, which this plan does not repeat.

**Branch:** `plan-14a-row-delivery-quote` off `main`.

---

## Critical context for the implementer

You know nothing about this codebase. Read this before touching anything.

**Money rules that are not negotiable:**

1. **Never auto-cancel or auto-release an order that has real money against it.** No TTL on the freight wait. This is the one data-loss-shaped bug this design could have.
2. **Any cash-in aggregate groups by currency.** Never a single scalar. NGN goods + USD freight summed is a confident wrong number.
3. **`Payment.purpose` defaults to `"goods"`.** Any `.payments` read this plan missed then keeps its current meaning. Fails safe.

**Expect this and do not "fix" it:** every RoW goods payment arrives *short*, because international wires lose a slice to intermediary banks (`payments/services.py:343` already says so). It routes through `accept_discrepancy`. That is known, documented in the spec, and **out of scope**. Do not widen the amount-matching tolerance. Do not add a tolerance band.

**Process rules, learned the hard way on Plan-09b:**

- **Run tasks serially.** Never run two implementation subagents in parallel — on Plan-09b two collided and one ran `git stash` against a tree with a live writer. Nothing was lost by luck.
- **Scope your test runs to your own app** (`pytest apps/delivery`), never the full suite, while other work may be in flight.
- **Mutation-verify every test you write.** Invert the branch you just covered and confirm your test goes red. Plan-09b found a branch invertible with 110 tests still green. If inverting the branch leaves your test green, the test does not exist.
- **Restart the docker stack before believing any red suite.** A dead `docker compose -f docker-compose.dev.yml` reports hundreds of DB errors that are pure infrastructure.
- **wp-cli-style ownership gotcha does not apply here** (that's the legacy WP server), but do not run Django management commands as root in the container.

**Commands:**

```bash
cd tokecosmetics-platform/backend
pytest apps/delivery -q          # scope to your app
ruff check .                     # must be clean before every commit
python manage.py makemigrations  # never hand-number migrations
```

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `backend/apps/delivery/models.py` | + `quote_required`, `disclaimer` on `DeliveryOption` | 2 |
| `backend/apps/delivery/migrations/0004_quote_required.py` | schema | 2 |
| `backend/apps/delivery/services.py` | country resolution, currency filter, `price: None` | 1, 2, 3 |
| `backend/apps/delivery/admin.py` | expose the two new fields | 3 |
| `backend/apps/checkout/views.py:52` | pass `request.country` | 1 |
| `backend/apps/checkout/services/checkout.py:92,123` | pass `country`; coerce quote_required delivery to 0; create the quote | 1, 5 |
| `backend/apps/shipping/models.py` | **new app** — `ShippingQuote` | 4 |
| `backend/apps/shipping/services.py` | `quote_freight`, `waive_freight` (6), `record_freight_receipt` (8), `cancel_quote` (9) | 6, 8, 9 |
| `backend/apps/payments/models.py` | + `Payment.purpose` | 7 |
| `backend/apps/payments/views.py:119,172,196` | scope pickers to `purpose="goods"` | 7 |
| `backend/apps/orders/models.py` | `Order.is_shippable` property | 10 |
| `backend/apps/shipping/views.py` + `admin_urls.py` | admin endpoints | 11 |
| `backend/apps/orders/templates/…/order_received.*` | OUR-charges paragraph | 12 |
| `docs/architecture.md` | § RoW freight quotes | 13 |

**Task order is a dependency chain, not a preference.** Task 7 (`Payment.purpose` + scoped pickers) MUST land before Task 8 creates the first freight `Payment` — otherwise a freight row immediately shadows the goods payment in `ConfirmManualReceiptView`. Task 4 (the model) before Task 5 (which creates rows). Task 1 before Task 2 (Task 2's currency filter needs the `country` parameter Task 1 threads through).

**A new `shipping` app**, not a bolt-on to `delivery`: `delivery` is pure pricing/matching domain with no order or money concepts, and `ShippingQuote` is an order-lifecycle money object. Keeping them apart preserves `delivery`'s "no Cart/Order import" property, which its module docstring explicitly claims.

---

### Task 0: Branch

- [ ] **Step 1: Cut the branch**

```bash
cd tokecosmetics-platform
git checkout main
git status --short          # must be empty
git checkout -b plan-14a-row-delivery-quote
```

---

### Task 1: `options_for_address` resolves the address country

**Why:** a `DE` address matches no `Country` row ⇒ zero options ⇒ `delivery_option_invalid`. A real RoW customer cannot check out today. Existing tests miss it because they pass `country_code="ZZ"`, which is not a real ISO code.

**Files:**
- Modify: `backend/apps/delivery/services.py:58-82`
- Modify: `backend/apps/checkout/views.py:52-53`
- Modify: `backend/apps/checkout/services/checkout.py:92`
- Test: `backend/apps/delivery/tests/test_matching.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/delivery/tests/test_matching.py`:

```python
@pytest.mark.django_db
def test_unknown_iso_code_falls_back_to_rest_of_world():
    """A German address must reach the ZZ option. This is the bug: DE matches no
    Country row and no Region, so the customer got zero options and could not check out."""
    zz = Country.objects.get(code="ZZ")
    opt = DeliveryOption.objects.create(
        name="International Standard", kind="manual", price=Decimal("25.00"),
        currency=zz.currency, min_days=3, max_days=10,
    )
    opt.countries.add(zz)

    matched = options_for_address(FakeAddress("DE"), lines=[], subtotal=Decimal("0"), country=zz)

    assert [o["name"] for o in matched] == ["International Standard"]


@pytest.mark.django_db
def test_known_country_with_no_options_does_not_fall_back_to_rest_of_world():
    """The fallback trigger is UNKNOWN COUNTRY CODE, never ZERO OPTIONS FOUND.
    If deactivating every GB option silently served GB customers the ZZ option,
    Britons would be charged international rates instead of checkout stopping."""
    zz = Country.objects.get(code="ZZ")
    gb = Country.objects.get(code="GB")
    opt = DeliveryOption.objects.create(
        name="International Standard", kind="manual", price=Decimal("25.00"),
        currency=zz.currency, min_days=3, max_days=10,
    )
    opt.countries.add(zz)

    matched = options_for_address(FakeAddress("GB"), lines=[], subtotal=Decimal("0"), country=gb)

    assert matched == []


@pytest.mark.django_db
def test_rest_of_world_address_never_matches_a_nigerian_region_option():
    """Region matching is ORed with country matching. A DE address must not pick up
    'Isolo area ₦1000' through the region leg."""
    zz = Country.objects.get(code="ZZ")
    lagos = Region.objects.create(country_code="NG", name="Lagos", level="state")
    ng_opt = DeliveryOption.objects.create(
        name="Isolo area delivery", kind="manual", price=Decimal("1000.00"),
        currency=Currency.objects.get(code="NGN"), min_days=1, max_days=2,
    )
    ng_opt.regions.add(lagos)

    matched = options_for_address(FakeAddress("DE"), lines=[], subtotal=Decimal("0"), country=zz)

    assert matched == []
```

`FakeAddress` already exists in this file. Confirm it exposes `country_code`, `area_region` and `state_region` (the last two `None`); if it does not, extend it — do not invent a second fake.

Imports needed at the top of the file: `from apps.core.models import Country, Currency, Region` and `from apps.delivery.models import DeliveryOption`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd tokecosmetics-platform/backend
pytest apps/delivery/tests/test_matching.py -q
```

Expected: FAIL — `options_for_address() got an unexpected keyword argument 'country'`.

- [ ] **Step 3: Implement**

In `backend/apps/delivery/services.py`, replace `options_for_address` (line 58) with:

```python
def options_for_address(address, lines, subtotal: Decimal, country) -> list[dict]:
    """Return the active delivery options serving this address, each with a computed
    price and ETA. `lines` = iterable of (ProductVariant, qty); `subtotal` in the
    order currency (for free_over); `country` is the ORDER's country (browsing
    context), which is not necessarily the address's.

    The address's country is resolved through the same resolve_country() used for
    pricing context, so delivery and currency can never disagree about what country
    an address is in. An unknown/inactive ISO code (a real "DE") resolves to the
    Rest-of-World row; a KNOWN country with no options configured returns [] and the
    caller raises delivery_option_invalid. The trigger is an unknown code, never an
    empty result — "no options found ⇒ use ZZ" would silently serve international
    pricing to GB customers the day someone deactivates the last GB option.
    """
    from apps.core.country_context import resolve_country

    resolved = resolve_country(address.country_code)
    if resolved is None:
        return []
    region_ids = _covered_region_ids(address)
    qs = (
        DeliveryOption.objects.filter(is_active=True)
        .filter(_coverage_q(resolved.code, region_ids))
        .prefetch_related("rates", "countries", "regions")
        .distinct()
        .order_by("sort", "name")
    )
    weight_g = _total_weight_g(lines)
    return [
        {
            "id": o.id,
            "name": o.name,
            "kind": o.kind,
            "currency": o.currency_id,
            "price": str(_price_for(o, weight_g, subtotal)),
            "min_days": o.min_days,
            "max_days": o.max_days,
        }
        for o in qs
    ]
```

The `country` parameter is unused in this task — Task 2 uses it. It is introduced now so both call sites move once.

- [ ] **Step 4: Fix the region leak**

The third test still fails: `_covered_region_ids` walks `address.area_region` / `state_region`, which are `None` for a `FakeAddress("DE")`, so `region_ids` is empty and the Lagos option is not matched — the test passes for the wrong reason. Make the guard real. In `_coverage_q`, the region leg must be constrained to the resolved country:

```python
def _coverage_q(country_code: str, region_ids: set[int]):
    """An option matches when it covers the address's resolved country OR any covered
    region (the address's own region or any ancestor). The region leg is constrained to
    the same country: a Region carries its own country_code, and without this an option
    attached only to a Lagos region could be reached by a non-NG address that somehow
    carried an NG region FK."""
    q = Q(countries__code=country_code)
    if region_ids:
        q |= Q(regions__id__in=region_ids, regions__country_code=country_code)
    return q
```

- [ ] **Step 5: Update the two call sites**

`backend/apps/checkout/views.py:52-53`:

```python
        totals = compute_totals(lines, request.country)
        return Response(options_for_address(address, lines, totals.subtotal, request.country))
```

`backend/apps/checkout/services/checkout.py:92`:

```python
        options = options_for_address(address, lines, subtotal_preview, country)
```

- [ ] **Step 6: Update the existing callers in tests**

`test_matching.py` and `test_pricing.py` call `options_for_address(addr, lines=[], subtotal=Decimal("0"))` at lines 58, 68, 79, 80, 90 and 32, 44, 52. Each needs `country=`. Pass the country the test's options belong to — e.g. `Country.objects.get(code="NG")` for the NG fixtures. **Do not** add a default value to the parameter to avoid touching them: a default would let a future caller silently skip the currency filter Task 2 adds, which is the money bug.

- [ ] **Step 7: Run the delivery + checkout suites**

```bash
pytest apps/delivery apps/checkout -q
```

Expected: PASS.

- [ ] **Step 8: Mutation-verify**

Change `_coverage_q`'s country leg to `Q(countries__code=address.country_code)` (the old raw behaviour). Confirm `test_unknown_iso_code_falls_back_to_rest_of_world` goes RED. Revert.

- [ ] **Step 9: Commit**

```bash
git add apps/delivery apps/checkout
git commit -m "fix: resolve RoW addresses to the ZZ country row in delivery matching

A real Rest-of-World address (country_code='DE') matched no Country row and no
Region, so options_for_address returned nothing and checkout hard-failed with
delivery_option_invalid. Existing tests missed it by using country_code='ZZ',
which is not a real ISO code.

Resolves the address country through the same resolve_country() used for pricing
context. Unknown code -> ZZ; a known country with zero options still returns []
so the caller fails loudly rather than serving international pricing.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Filter delivery options to the order's currency

**Why:** `checkout.py:123` does `compute_totals(..., delivery_amount=Decimal(chosen["price"]))` — it takes the option's **price** and ignores its **currency**. Order currency comes from the browsing header; the option comes from the shipping address. A ₦-context customer shipping to Germany would get the $25 ZZ option added to an NGN order as ₦25 — freight to Germany charged at three pence. Unreachable before Task 1; live after it.

**Owner's decision:** block it. Rejected: FX conversion (new rate source, new staleness bug) and currency-follows-address (re-prices the cart mid-checkout).

**Files:**
- Modify: `backend/apps/delivery/services.py`
- Test: `backend/apps/delivery/tests/test_matching.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_option_in_another_currency_is_never_offered():
    """The order currency comes from the browsing context; the option comes from the
    shipping address. A NGN-context customer shipping to Germany must NOT be offered
    the USD ZZ option — compute_totals would add its 25 to an NGN order as ₦25."""
    zz = Country.objects.get(code="ZZ")          # USD
    ng = Country.objects.get(code="NG")          # NGN
    opt = DeliveryOption.objects.create(
        name="International Standard", kind="manual", price=Decimal("25.00"),
        currency=zz.currency, min_days=3, max_days=10,
    )
    opt.countries.add(zz)

    # Browsing the NG storefront (order currency NGN), shipping to Germany (resolves ZZ).
    matched = options_for_address(FakeAddress("DE"), lines=[], subtotal=Decimal("0"), country=ng)

    assert matched == []
```

- [ ] **Step 2: Run it to verify it fails**

```bash
pytest apps/delivery/tests/test_matching.py::test_option_in_another_currency_is_never_offered -q
```

Expected: FAIL — one option returned, expected `[]`.

- [ ] **Step 3: Implement**

In `options_for_address`, add the currency filter to the queryset:

```python
    qs = (
        DeliveryOption.objects.filter(is_active=True)
        .filter(currency_id=country.currency_id)
        .filter(_coverage_q(resolved.code, region_ids))
        .prefetch_related("rates", "countries", "regions")
        .distinct()
        .order_by("sort", "name")
    )
```

Extend the docstring:

```python
    Options are filtered to the ORDER's currency. compute_totals takes a bare
    delivery amount and knows nothing about the option's currency, so an option in
    another currency would have its number added to the order as if it were the
    order's currency. Blocking is deliberate (see the spec): converting via an FX
    rate would put FX into the totals maths for a rare case.
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/delivery apps/checkout -q
```

Expected: PASS.

- [ ] **Step 5: Mutation-verify**

Delete the `.filter(currency_id=country.currency_id)` line. Confirm the new test goes RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add apps/delivery
git commit -m "fix: only offer delivery options priced in the order's currency

compute_totals takes a bare delivery_amount and ignores the option's currency, so
a NGN-context order shipping to Germany would add the USD 25.00 ZZ option as ₦25.
Unreachable until the RoW matching fix; live after it.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `quote_required` + `disclaimer` on `DeliveryOption`

**Why:** `price=0` renders identically whether it means "I promise this costs nothing" or "I have no idea what this costs". Opposite meanings; the customer sees only the number. This field stops unknown cost masquerading as zero cost. Genuine ₦0 free delivery stays untouched.

**Files:**
- Modify: `backend/apps/delivery/models.py`
- Modify: `backend/apps/delivery/services.py`
- Create: `backend/apps/delivery/migrations/0004_quote_required.py` (via `makemigrations`)
- Modify: `backend/apps/delivery/admin.py`
- Test: `backend/apps/delivery/tests/test_pricing.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/apps/delivery/tests/test_pricing.py`:

```python
@pytest.mark.django_db
def test_quote_required_option_emits_no_price():
    """price MUST be None, not '0.00'. A zero renders as 'Free' and becomes a promise
    the business cannot keep; None makes any frontend that does arithmetic on it break
    loudly instead of silently lying to the customer."""
    zz = Country.objects.get(code="ZZ")
    opt = DeliveryOption.objects.create(
        name="Adex International delivery", kind="manual", price=Decimal("0.00"),
        currency=zz.currency, min_days=7, max_days=21,
        quote_required=True,
        disclaimer="Shipping quoted after you order — typically $35–70 to Europe.",
    )
    opt.countries.add(zz)

    [result] = options_for_address(FakeAddress("DE"), lines=[], subtotal=Decimal("0"), country=zz)

    assert result["price"] is None
    assert result["quote_required"] is True
    assert result["disclaimer"] == "Shipping quoted after you order — typically $35–70 to Europe."


@pytest.mark.django_db
def test_free_over_never_applies_to_a_quote_required_option():
    """free_over turning an unknown cost into a stated 'Free' is the exact false
    promise this field exists to prevent."""
    zz = Country.objects.get(code="ZZ")
    opt = DeliveryOption.objects.create(
        name="Adex International delivery", kind="manual", price=Decimal("0.00"),
        currency=zz.currency, min_days=7, max_days=21, quote_required=True,
        free_over=Decimal("100.00"), disclaimer="Quoted after you order.",
    )
    opt.countries.add(zz)

    [result] = options_for_address(
        FakeAddress("DE"), lines=[], subtotal=Decimal("500.00"), country=zz
    )

    assert result["price"] is None


@pytest.mark.django_db
def test_normal_option_still_emits_a_price_string():
    """Regression guard: a genuine ₦0 'Free Delivery' must still work exactly as before.
    The owner's stated principle — name + amount, possibly zero — is unchanged."""
    ng = Country.objects.get(code="NG")
    opt = DeliveryOption.objects.create(
        name="Free Delivery", kind="manual", price=Decimal("0.00"),
        currency=ng.currency, min_days=1, max_days=3,
    )
    opt.countries.add(ng)

    [result] = options_for_address(FakeAddress("NG"), lines=[], subtotal=Decimal("0"), country=ng)

    assert result["price"] == "0.00"
    assert result["quote_required"] is False
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest apps/delivery/tests/test_pricing.py -q
```

Expected: FAIL — `DeliveryOption() got unexpected keyword arguments: 'quote_required'`.

- [ ] **Step 3: Add the fields**

In `backend/apps/delivery/models.py`, inside `DeliveryOption`, after `free_over`:

```python
    # "The cost is unknown and will be quoted after the order" — NOT "the cost is zero".
    # Those are opposite meanings that a bare price=0 renders identically, and the
    # customer only ever sees the number. When true, services.py emits price=None so
    # there is no figure any client can render as "Free".
    quote_required = models.BooleanField(default=False)
    # Customer-visible text shown INSTEAD of a price. Carry an indicative range here
    # ("typically $35–70 to Europe") — it is the single biggest lever on the rate at
    # which customers decline the quote after they have already paid for goods.
    disclaimer = models.CharField(max_length=200, blank=True)
```

- [ ] **Step 4: Emit them from `options_for_address`**

In the dict comprehension in `services.py`:

```python
    return [
        {
            "id": o.id,
            "name": o.name,
            "kind": o.kind,
            "currency": o.currency_id,
            # None, never "0.00": an unknown cost must not be renderable as "Free".
            "price": None if o.quote_required else str(_price_for(o, weight_g, subtotal)),
            "quote_required": o.quote_required,
            "disclaimer": o.disclaimer,
            "min_days": o.min_days,
            "max_days": o.max_days,
        }
        for o in qs
    ]
```

- [ ] **Step 5: Migration**

```bash
python manage.py makemigrations delivery
```

Expected: `0004_deliveryoption_disclaimer_deliveryoption_quote_required.py`. Both fields have defaults, so no `RunPython` and no interactive prompt.

- [ ] **Step 6: Admin**

In `backend/apps/delivery/admin.py`, add `quote_required` and `disclaimer` to the `DeliveryOption` admin's `fields`/`list_display` following whatever pattern is already there. Add `quote_required` to `list_filter`. Do not restructure the admin.

- [ ] **Step 7: Run tests**

```bash
pytest apps/delivery -q
```

Expected: PASS.

- [ ] **Step 8: Mutation-verify**

Change `"price": None if o.quote_required else ...` to always emit the price string. Confirm `test_quote_required_option_emits_no_price` goes RED. Revert.

- [ ] **Step 9: Commit**

```bash
git add apps/delivery
git commit -m "feat: quote_required delivery options carry a disclaimer, not a price

price=0 renders identically whether it means 'this costs nothing' or 'the cost is
unknown'. Emits price=None for a quote_required option so no client can render it
as Free, and suppresses free_over. Genuine ₦0 free delivery is unchanged.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: The `shipping` app and the `ShippingQuote` model

**Why a new app:** `delivery/services.py`'s docstring claims "Pure domain: no HTTP, no Cart import". `ShippingQuote` is an order-lifecycle money object. Putting it in `delivery` would break that property.

**Files:**
- Create: `backend/apps/shipping/__init__.py`, `apps.py`, `models.py`, `admin.py`, `migrations/__init__.py`
- Create: `backend/apps/shipping/tests/__init__.py`, `tests/test_models.py`
- Modify: `backend/config/settings/base.py` (add to `INSTALLED_APPS` — find the exact module path; the other apps are listed as `apps.delivery` etc.)

- [ ] **Step 1: Write the failing test**

`backend/apps/shipping/tests/test_models.py`:

```python
from decimal import Decimal

import pytest

from apps.shipping.models import ShippingQuote


@pytest.mark.django_db
def test_quote_is_born_awaiting_quote(order_factory):
    """The row exists from order placement, BEFORE anyone quotes. If it were created
    at quote time, 'orders awaiting a freight quote' would be a NOT EXISTS query — an
    absence, which no admin screen surfaces and nobody notices, while a paid order
    sits silent and the customer waits. A row that exists is a work queue."""
    order = order_factory()

    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    assert quote.status == "awaiting_quote"
    assert quote.amount is None
    assert quote.is_settled is False


@pytest.mark.django_db
def test_one_quote_per_order(order_factory):
    order = order_factory()
    ShippingQuote.objects.create(order=order, currency=order.currency)

    with pytest.raises(Exception):  # IntegrityError under the OneToOne constraint
        ShippingQuote.objects.create(order=order, currency=order.currency)


@pytest.mark.parametrize(
    "status,settled",
    [("awaiting_quote", False), ("quoted", False), ("paid", True), ("waived", True),
     ("cancelled", True)],
)
@pytest.mark.django_db
def test_is_settled(order_factory, status, settled):
    """is_settled drives Order.is_shippable. awaiting_quote and quoted are NOT settled:
    the order must not ship while freight is unpaid."""
    order = order_factory()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency, status=status)

    assert quote.is_settled is settled
```

`order_factory` — check `backend/apps/orders/factories.py` and `conftest.py` for the existing fixture name and reuse it. Do not write a new factory.

- [ ] **Step 2: Run to verify failure**

```bash
pytest apps/shipping -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'apps.shipping'`.

- [ ] **Step 3: Scaffold the app**

```bash
cd tokecosmetics-platform/backend
python manage.py startapp shipping apps/shipping
```

Set `name = "apps.shipping"` in `apps/shipping/apps.py`, mirroring `apps/delivery/apps.py`. Add `"apps.shipping"` to `INSTALLED_APPS`. Delete the generated `views.py`/`tests.py` boilerplate; create `tests/__init__.py`.

- [ ] **Step 4: The model**

`backend/apps/shipping/models.py`:

```python
from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class ShippingQuote(TimeStampedModel):
    """The freight OBLIGATION for one order — a negotiated promise, not money.

    Deliberately NOT a Payment row. The cash the customer eventually transfers for
    freight IS a Payment (purpose="freight"); this is what we ASKED for. Keeping the
    two apart is what makes `amount` (quoted) and `payment.amount` (actually landed)
    structurally different numbers, which they are: an international wire quoted at
    €40 delivers ~€32 after correspondent fees. A single-amount design would have
    nowhere to put that gap and would silently under-report cash.

    A `quoted` status also has no business in Payment.STATUSES: when the four
    networked gateways reactivate, that enum is gateway-shaped (initiated/succeeded/
    failed), and a row meaning "quoted, no money has moved" would pollute it forever.
    """

    STATUSES = [
        ("awaiting_quote", "Awaiting quote"),   # created at order placement
        ("quoted", "Quoted"),                   # customer has been told the figure
        ("paid", "Paid"),                       # freight cash recorded
        ("waived", "Waived"),                   # merchant absorbed it — requires a prior quote
        ("cancelled", "Cancelled"),             # declined OR never answered — same handling
    ]
    # Nothing further happens to the order on these; is_shippable stops blocking.
    SETTLED = frozenset({"paid", "waived", "cancelled"})

    order = models.OneToOneField(
        "orders.Order", on_delete=models.PROTECT, related_name="shipping_quote"
    )
    # null until quoted — the whole point of awaiting_quote is that no figure exists yet.
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    status = models.CharField(max_length=20, default="awaiting_quote", choices=STATUSES)
    quoted_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    # APPEND-ONLY. Re-quoting ("can you try someone cheaper?") overwrites `amount`, so
    # the note is the only trail of what was previously promised. Never assign to it —
    # always append. Same erasure class as Plan-09b's _flag_review bug.
    note = models.TextField(blank=True)

    class Meta:
        indexes = [
            # The work queue: "orders I have not quoted yet" and "quoted, awaiting money".
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"freight {self.amount or '—'} {self.currency_id} ({self.status}) for {self.order_id}"

    @property
    def is_settled(self) -> bool:
        return self.status in self.SETTLED
```

- [ ] **Step 5: Migration**

```bash
python manage.py makemigrations shipping
```

- [ ] **Step 6: Run tests**

```bash
pytest apps/shipping -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/shipping config
git commit -m "feat: add shipping app with the ShippingQuote obligation model

The freight quote is an obligation, not money. The cash lands later as a Payment
(purpose=freight), so quoted-vs-received is structurally two numbers — an intl wire
quoted at €40 delivers ~€32 after correspondent fees, and a single-amount design
would silently under-report cash.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Create the quote at order placement

**Files:**
- Modify: `backend/apps/checkout/services/checkout.py:92-150`
- Test: `backend/apps/checkout/tests/test_row_checkout.py` (create)

- [ ] **Step 1: Write the failing tests**

`backend/apps/checkout/tests/test_row_checkout.py`:

```python
from decimal import Decimal

import pytest

from apps.shipping.models import ShippingQuote


@pytest.mark.django_db
def test_row_order_is_born_with_an_awaiting_quote_row(row_checkout):
    """Created at placement, not at quote time — see ShippingQuote's docstring."""
    result = row_checkout()

    quote = ShippingQuote.objects.get(order=result.order)
    assert quote.status == "awaiting_quote"
    assert quote.amount is None
    assert quote.currency_id == result.order.currency_id


@pytest.mark.django_db
def test_row_order_total_excludes_freight(row_checkout):
    """The customer pays goods only. shipping_total is 0.00 and the grand total is
    what the bank-details email quotes and what staff match the transfer against."""
    result = row_checkout()

    assert result.order.shipping_total == Decimal("0.00")
    assert result.order.grand_total == result.order.subtotal


@pytest.mark.django_db
def test_normal_order_gets_no_shipping_quote(ng_checkout):
    """Only quote_required options create a quote. A ₦3500 Lagos delivery must not."""
    result = ng_checkout()

    assert not ShippingQuote.objects.filter(order=result.order).exists()
```

Write a `row_checkout` / `ng_checkout` fixture in `backend/apps/checkout/tests/conftest.py` (or extend the existing one) that drives `place_order` end-to-end. **Use `country_code="DE"` on the RoW address** — never `"ZZ"`. That substitution is the exact reason the original bug shipped.

- [ ] **Step 2: Run to verify failure**

```bash
pytest apps/checkout/tests/test_row_checkout.py -q
```

Expected: FAIL — `ShippingQuote.DoesNotExist`.

- [ ] **Step 3: Implement**

In `checkout.py`, `chosen` is the option dict from `options_for_address`, so it now carries `quote_required` and `price: None`. `Decimal(chosen["price"])` at line 123 would raise `TypeError` on `None`. Change line 123:

```python
        # A quote_required option has no price yet — the customer pays goods only and
        # the freight is quoted afterwards (see the ShippingQuote created below). Coerce
        # to 0 for the goods total rather than letting Decimal(None) raise.
        delivery_amount = (
            Decimal("0.00") if chosen["quote_required"] else Decimal(chosen["price"])
        )
        totals = compute_totals(lines, country, delivery_amount=delivery_amount, coupon=coupon)
```

After `record_event(order, "placed", ...)` (line 153), inside the same transaction:

```python
        if chosen["quote_required"]:
            # Born at placement, in the same transaction as the order: the awaiting_quote
            # queue is how staff learn this order needs a freight quote at all. Created
            # later (at quote time) it would be an absence, and absences are invisible.
            from apps.shipping.models import ShippingQuote

            ShippingQuote.objects.create(order=order, currency=country.currency)
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/checkout apps/shipping -q
```

Expected: PASS.

- [ ] **Step 5: Mutation-verify**

Change `if chosen["quote_required"]:` to `if False:`. Confirm `test_row_order_is_born_with_an_awaiting_quote_row` goes RED. Revert.

- [ ] **Step 6: Commit**

```bash
git add apps/checkout apps/shipping
git commit -m "feat: create a ShippingQuote at placement for quote_required options

The customer pays goods only; shipping_total is 0.00. The awaiting_quote row is
born in the placement transaction so the work queue is a positive filter rather
than a NOT EXISTS on an absence nobody notices.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `quote_freight` and `waive_freight`

**Files:**
- Create: `backend/apps/shipping/services.py`
- Test: `backend/apps/shipping/tests/test_services.py`

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal

import pytest

from apps.shipping.models import ShippingQuote
from apps.shipping.services import ShippingError, quote_freight, waive_freight


@pytest.mark.django_db
def test_quote_sets_amount_and_status(order_factory, staff_user):
    order = order_factory()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    quote_freight(quote, staff_user=staff_user, amount=Decimal("40.00"), note="Adex")

    quote.refresh_from_db()
    assert quote.status == "quoted"
    assert quote.amount == Decimal("40.00")
    assert quote.quoted_at is not None


@pytest.mark.django_db
def test_requoting_appends_to_note_and_never_erases_the_trail(order_factory, staff_user):
    """Re-quoting overwrites `amount`, so `note` is the ONLY record of what was
    previously promised. Assigning instead of appending is the Plan-09b _flag_review
    money-loss bug, one model over."""
    order = order_factory()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    quote_freight(quote, staff_user=staff_user, amount=Decimal("40.00"), note="Adex")
    quote_freight(quote, staff_user=staff_user, amount=Decimal("28.00"), note="cheaper forwarder")

    quote.refresh_from_db()
    assert quote.amount == Decimal("28.00")
    assert "40.00" in quote.note        # the superseded figure survives
    assert "Adex" in quote.note
    assert "cheaper forwarder" in quote.note


@pytest.mark.django_db
def test_waiving_without_a_prior_quote_is_refused(order_factory, staff_user):
    """Waiving a charge with no amount records NOTHING — that is literally the
    off-books hole this design exists to close, re-entered through the front door.
    Quote-then-waive forces the artifact to read '₦18,400 of freight forgiven'."""
    order = order_factory()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    with pytest.raises(ShippingError) as exc:
        waive_freight(quote, staff_user=staff_user, note="goodwill")

    assert exc.value.code == "quote_required_before_waive"
    quote.refresh_from_db()
    assert quote.status == "awaiting_quote"


@pytest.mark.django_db
def test_waiving_after_a_quote_records_the_forgiven_amount(order_factory, staff_user):
    order = order_factory()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff_user, amount=Decimal("40.00"), note="Adex")

    waive_freight(quote, staff_user=staff_user, note="goodwill — repeat customer")

    quote.refresh_from_db()
    assert quote.status == "waived"
    assert quote.amount == Decimal("40.00")     # the forgiven value is still legible
    assert quote.settled_at is not None


@pytest.mark.django_db
def test_waiving_requires_a_reason(order_factory, staff_user):
    order = order_factory()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff_user, amount=Decimal("40.00"), note="Adex")

    with pytest.raises(ShippingError) as exc:
        waive_freight(quote, staff_user=staff_user, note="")

    assert exc.value.code == "reason_required"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest apps/shipping/tests/test_services.py -q
```

Expected: FAIL — `ModuleNotFoundError: apps.shipping.services`.

- [ ] **Step 3: Implement**

`backend/apps/shipping/services.py`:

```python
"""Freight quote lifecycle. The quote is an OBLIGATION — no money moves here. The
freight cash is recorded separately (record_freight_receipt) as a Payment."""
from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.orders.state import record_event


class ShippingError(Exception):
    def __init__(self, code: str, detail: str = "", http: int = 400):
        self.code = code
        self.detail = detail or code
        self.http = http
        super().__init__(self.detail)


def _append_note(quote, text: str) -> None:
    """APPEND, never assign. Re-quoting overwrites `amount`; this is the only trail of
    what was promised before. Plan-09b lost money to exactly this bug (_flag_review
    assigned over an earlier flag, so staff refunded ₦2k on an order owing ₦12k)."""
    stamp = timezone.now().strftime("%Y-%m-%d %H:%M")
    quote.note = f"{quote.note}\n[{stamp}] {text}".strip()


def quote_freight(quote, *, staff_user, amount: Decimal, note: str = "") -> None:
    """Record what the forwarder quoted and move to `quoted`. Re-quoting a `quoted` row
    is allowed and expected ("can you try someone cheaper?")."""
    if quote.is_settled:
        raise ShippingError("quote_already_settled",
                            f"This freight quote is already {quote.status}.")
    if amount <= Decimal("0"):
        raise ShippingError("invalid_amount", "A freight quote must be greater than zero.")

    previous = f" (was {quote.amount})" if quote.amount is not None else ""
    quote.amount = amount
    quote.status = "quoted"
    quote.quoted_at = timezone.now()
    _append_note(quote, f"quoted {amount} {quote.currency_id}{previous} by "
                        f"{staff_user.get_username()}: {note}")
    quote.save(update_fields=["amount", "status", "quoted_at", "note", "updated_at"])
    record_event(quote.order, "freight_quoted", actor=staff_user,
                 message=f"{amount} {quote.currency_id}: {note}")


def waive_freight(quote, *, staff_user, note: str) -> None:
    """Merchant absorbs the freight. Requires a PRIOR QUOTE: waiving an unquoted charge
    records nothing, which is the off-books hole this whole design closes. It must read
    "₦18,400 of freight forgiven", never silence.

    Every escape hatch in this codebase gets worn smooth (accept_discrepancy, W001).
    The mandatory reason is table stakes; the reporting line (see docs) is what makes
    this safe."""
    if quote.is_settled:
        raise ShippingError("quote_already_settled",
                            f"This freight quote is already {quote.status}.")
    if quote.amount is None:
        raise ShippingError(
            "quote_required_before_waive",
            "Quote the freight first, so the waiver records what was forgiven.",
        )
    if not note.strip():
        raise ShippingError("reason_required", "A reason is required to waive freight.")

    quote.status = "waived"
    quote.settled_at = timezone.now()
    _append_note(quote, f"waived {quote.amount} {quote.currency_id} by "
                        f"{staff_user.get_username()}: {note}")
    quote.save(update_fields=["status", "settled_at", "note", "updated_at"])
    record_event(quote.order, "freight_waived", actor=staff_user,
                 message=f"{quote.amount} {quote.currency_id} forgiven: {note}")
```

Check `apps/orders/state.py` for `record_event`'s real signature before using it — Plan-09b's spec got its location wrong (it is in `state.py`, NOT `orders/services.py`). Match the actual parameters.

- [ ] **Step 4: Run tests**

```bash
pytest apps/shipping -q
```

Expected: PASS.

- [ ] **Step 5: Mutation-verify**

In `_append_note`, change the body to `quote.note = text` (assign instead of append). Confirm `test_requoting_appends_to_note_and_never_erases_the_trail` goes RED. Revert.

- [ ] **Step 6: Commit**

```bash
git add apps/shipping
git commit -m "feat: quote_freight and waive_freight

Notes append, never assign — re-quoting overwrites amount and the note is the only
trail of what was promised (the Plan-09b _flag_review erasure class). Waiving
requires a prior quote so the record reads '₦18,400 forgiven' rather than silence.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `Payment.purpose` and scoping the payment pickers

**Why:** `payments/views.py:196` picks `filter(gateway="bank_transfer").order_by("-id").first()` — the **newest**. A freight Payment would **shadow the goods payment**, so staff confirming a bank transfer would confirm the wrong row. Both refund pickers have the same shape. This task must land **before** Task 8 creates any freight Payment.

**Files:**
- Modify: `backend/apps/payments/models.py`
- Create: `backend/apps/payments/migrations/0008_payment_purpose.py` (via `makemigrations`)
- Modify: `backend/apps/payments/views.py:119, 172, 196`
- Test: `backend/apps/payments/tests/test_payment_purpose.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal

import pytest

from apps.payments.models import Payment


@pytest.mark.django_db
def test_existing_payments_default_to_goods():
    """The default MUST be goods, not null: any .payments read this plan missed keeps
    its current meaning by default. Fails safe."""
    assert Payment._meta.get_field("purpose").default == "goods"


@pytest.mark.django_db
def test_confirm_view_never_picks_a_freight_payment(admin_client, order_factory):
    """views.py:196 picks the NEWEST bank_transfer payment. A freight row is newer than
    the goods row, so without scoping, staff clicking 'confirm payment' would confirm
    freight against the goods total."""
    order = order_factory(status="pending_payment", grand_total=Decimal("5000.00"))
    goods = Payment.objects.create(
        order=order, gateway="bank_transfer", amount=Decimal("5000.00"),
        currency=order.currency, status="initiated", idempotency_key="k-goods",
        purpose="goods",
    )
    freight = Payment.objects.create(
        order=order, gateway="bank_transfer", amount=Decimal("40.00"),
        currency=order.currency, status="succeeded", idempotency_key="k-freight",
        purpose="freight",
    )
    assert freight.pk > goods.pk        # the shadowing precondition

    response = admin_client.post(
        f"/api/v1/admin/orders/{order.number}/confirm-payment/",
        {"amount_received": "5000.00", "bank_reference": "REF-1"},
        content_type="application/json",
    )

    assert response.status_code == 200
    goods.refresh_from_db()
    freight.refresh_from_db()
    assert goods.status == "succeeded"
    assert freight.amount == Decimal("40.00")   # untouched
```

Check `apps/payments/tests/` for the existing admin-client fixture name and the real URL prefix (`admin_urls.py` is mounted somewhere in `config/urls.py` — confirm it) before writing this. Reuse existing fixtures.

- [ ] **Step 2: Run to verify failure**

```bash
pytest apps/payments/tests/test_payment_purpose.py -q
```

Expected: FAIL — `Payment() got an unexpected keyword argument 'purpose'`.

- [ ] **Step 3: Add the field**

In `backend/apps/payments/models.py`, inside `Payment`, after `gateway`:

```python
    PURPOSES = [("goods", "Goods"), ("freight", "Freight")]
    # What this money is FOR. Default "goods" is load-bearing: every pre-existing row and
    # every .payments read that was not updated keeps its original meaning, so a missed
    # call site fails safe rather than silently mixing freight into goods maths.
    # A freight row is created ONLY by shipping.services.record_freight_receipt, which
    # never calls confirm_manual_receipt — the amount-match, accept_discrepancy and
    # duplicate-reference controls live in that SERVICE, not in this model, so freight
    # cannot reach them.
    purpose = models.CharField(max_length=10, default="goods", choices=PURPOSES)
```

- [ ] **Step 4: Migration**

```bash
python manage.py makemigrations payments
```

The field has a default, so existing rows backfill to `"goods"` automatically. No `RunPython`.

- [ ] **Step 5: Scope the three pickers**

`backend/apps/payments/views.py:196` (`ConfirmManualReceiptView.post`):

```python
        payment = (
            order.payments.filter(gateway="bank_transfer", purpose="goods")
            .order_by("-id").first()
        )
```

`backend/apps/payments/views.py:117-122` (`OrderRefundView._pick_payment`) and `:170-175` (`ManualRefundView._pick_payment`) — both bodies become:

```python
    @staticmethod
    def _pick_payment(order, payment_id):
        # purpose="goods": a freight receipt is not what a refund of this order means,
        # and it must never be picked implicitly. An explicit payment_id can still
        # reach it — that is a deliberate staff choice, not a default.
        payments = order.payments.filter(purpose="goods")
        if payment_id:
            return order.payments.filter(pk=payment_id).first()
        return payments.filter(status__in=["succeeded", "partially_refunded"]).first()
```

**Not touched:** `checkout/tasks.py:52` reads `order.payments.all()` but only for orders in `pending_payment`; a freight row only ever exists on an order that has already been paid and moved on, so it is unreachable. Verified — leave it alone.

- [ ] **Step 6: Run tests**

```bash
pytest apps/payments -q
```

Expected: PASS.

- [ ] **Step 7: Mutation-verify**

Remove `purpose="goods"` from the `ConfirmManualReceiptView` filter. Confirm `test_confirm_view_never_picks_a_freight_payment` goes RED. Restore.

- [ ] **Step 8: Commit**

```bash
git add apps/payments
git commit -m "feat: Payment.purpose (goods|freight) and scope the payment pickers

views.py:196 picks the NEWEST bank_transfer payment, so a freight row would shadow
the goods payment and staff would confirm the wrong one. Both refund pickers had
the same shape. Defaults to goods so any missed .payments read fails safe.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: `record_freight_receipt`

**Why:** the freight cash must be a `Payment` so `sum(Payment)` grouped by currency stays the one true cash-in question. It does **not** call `confirm_manual_receipt` — the goods leg's controls live in that service and freight must not reach them.

**Files:**
- Modify: `backend/apps/shipping/services.py`
- Test: `backend/apps/shipping/tests/test_services.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_recording_a_receipt_creates_a_freight_payment(order_factory, staff_user):
    """Cash-in is sum(Payment) grouped by currency — ONE table. The freight receipt is
    a Payment; the quote is not."""
    from apps.payments.models import Payment

    order = order_factory()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff_user, amount=Decimal("40.00"), note="Adex")

    record_freight_receipt(
        quote, staff_user=staff_user, amount_received=Decimal("32.00"),
        bank_reference="TC-100001-F", note="short after correspondent fees",
    )

    payment = Payment.objects.get(order=order, purpose="freight")
    assert payment.amount == Decimal("32.00")      # what LANDED
    assert payment.status == "succeeded"
    assert payment.gateway == "bank_transfer"
    quote.refresh_from_db()
    assert quote.status == "paid"
    assert quote.amount == Decimal("40.00")        # what was ASKED — a different number


@pytest.mark.django_db
def test_quoted_and_received_are_allowed_to_differ_without_a_flag(order_factory, staff_user):
    """An intl wire quoted at €40 lands ~€32 after correspondent fees. That gap is
    NORMAL on the freight leg and must not raise, must not require accept_discrepancy,
    and must not flag the order for review — otherwise the review flag fires on every
    RoW order and becomes a keystroke (see payments.W001 crying wolf)."""
    order = order_factory()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff_user, amount=Decimal("40.00"), note="Adex")

    record_freight_receipt(
        quote, staff_user=staff_user, amount_received=Decimal("32.00"),
        bank_reference="TC-100001-F", note="",
    )

    order.refresh_from_db()
    assert order.review_reason == ""


@pytest.mark.django_db
def test_a_duplicate_bank_reference_is_refused(order_factory, staff_user):
    """One transfer quoted against two orders means goods ship twice against money
    that arrived once. A REAL unique constraint on a REAL column — not the
    raw_response JSON key that gave Plan-09b its TOCTOU race."""
    from django.db import IntegrityError

    o1, o2 = order_factory(), order_factory()
    for order in (o1, o2):
        q = ShippingQuote.objects.create(order=order, currency=order.currency)
        quote_freight(q, staff_user=staff_user, amount=Decimal("40.00"), note="Adex")

    record_freight_receipt(
        o1.shipping_quote, staff_user=staff_user, amount_received=Decimal("40.00"),
        bank_reference="DUP-1", note="",
    )
    with pytest.raises(IntegrityError):
        record_freight_receipt(
            o2.shipping_quote, staff_user=staff_user, amount_received=Decimal("40.00"),
            bank_reference="DUP-1", note="",
        )


@pytest.mark.django_db
def test_recording_a_receipt_before_quoting_is_refused(order_factory, staff_user):
    order = order_factory()
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)

    with pytest.raises(ShippingError) as exc:
        record_freight_receipt(
            quote, staff_user=staff_user, amount_received=Decimal("40.00"),
            bank_reference="X-1", note="",
        )

    assert exc.value.code == "quote_required_before_receipt"
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — `cannot import name 'record_freight_receipt'`.

- [ ] **Step 3: Implement**

Add to `backend/apps/shipping/services.py`:

```python
def record_freight_receipt(quote, *, staff_user, amount_received: Decimal,
                           bank_reference: str, note: str = "") -> None:
    """Record the freight cash that landed. Creates a Payment(purpose="freight").

    Deliberately does NOT call payments.services.confirm_manual_receipt. That service
    owns the goods leg's controls (three-way amount match, accept_discrepancy, the
    duplicate-reference check) and those controls must stay untouchable by freight.
    The isolation here comes from the CODE PATH, not from the table.

    quoted != received is NORMAL and raises nothing: an intl wire quoted at €40 lands
    ~€32 after correspondent fees. `quote.amount` is what we asked for; `payment.amount`
    is cash. Flagging that gap would fire the review flag on every single RoW order and
    train staff to dismiss it — the failure mode payments.W001 already demonstrates.
    """
    from apps.payments.models import Payment

    if quote.is_settled:
        raise ShippingError("quote_already_settled",
                            f"This freight quote is already {quote.status}.")
    if quote.amount is None:
        raise ShippingError("quote_required_before_receipt",
                            "Quote the freight before recording a receipt against it.")
    if amount_received <= Decimal("0"):
        raise ShippingError("invalid_amount", "A freight receipt must be greater than zero.")

    Payment.objects.create(
        order=quote.order,
        gateway="bank_transfer",
        purpose="freight",
        amount=amount_received,          # cash that LANDED, not what was quoted
        currency=quote.currency,
        status="succeeded",              # the transfer already happened; there is no pending phase
        gateway_reference=bank_reference,
        idempotency_key=f"freight:{quote.order.number}:{bank_reference}",
    )
    quote.status = "paid"
    quote.settled_at = timezone.now()
    _append_note(quote, f"received {amount_received} {quote.currency_id} "
                        f"(ref {bank_reference}) by {staff_user.get_username()}: {note}")
    quote.save(update_fields=["status", "settled_at", "note", "updated_at"])
    record_event(quote.order, "freight_received", actor=staff_user,
                 message=f"{amount_received} {quote.currency_id} (ref {bank_reference})")
```

The duplicate-reference guard is the **existing** `uniq_payment_gateway_reference` constraint on `(gateway, gateway_reference)` — a real DB constraint on a real column, which is exactly the fix Plan-09b wanted and could not have on a JSON key. No new constraint is needed. `IntegrityError` surfaces as a 409 in Task 11.

**Reference format:** `TC-100001-F` — the order number with an `-F` suffix, so goods and freight references cannot collide in `(gateway, gateway_reference)`. Be honest in the docs (Task 12) about what this buys: SWIFT narration is routinely truncated by intermediaries, so real-world matching is often by amount + date + name. The constraint is a **dedup** control, not an identification mechanism.

- [ ] **Step 4: Run tests**

```bash
pytest apps/shipping apps/payments -q
```

Expected: PASS.

- [ ] **Step 5: Mutation-verify**

Change `amount=amount_received` to `amount=quote.amount`. Confirm `test_recording_a_receipt_creates_a_freight_payment` goes RED (it would assert 40.00, not 32.00). Revert. **This is the single most important mutation check in the plan** — it is the exact bug that would silently make the books overstate cash.

- [ ] **Step 6: Commit**

```bash
git add apps/shipping
git commit -m "feat: record_freight_receipt creates a Payment(purpose=freight)

Cash-in stays sum(Payment) grouped by currency — one table. quote.amount is what we
asked for; payment.amount is what landed (an intl wire quoted at €40 delivers ~€32).
Deliberately does not call confirm_manual_receipt: the goods leg's controls live in
that service and freight must not reach them.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: `cancel_quote` — the decline path

**Why:** the customer declines the freight quote, or never replies. Silence is the modal case. Both collapse to one terminal `cancelled`.

**Build the record, not a refund flow.** `cancel_order` and `record_manual_refund` already exist.

**Files:**
- Modify: `backend/apps/shipping/services.py`
- Test: `backend/apps/shipping/tests/test_services.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_cancelling_a_quote_cancels_the_order_and_releases_stock(order_factory, staff_user):
    """Cosmetics have shelf life and trend risk — freeing the units is the part that
    actually recovers value. The goods refund is wired BY HAND through the existing
    manual-refund endpoint; this does not attempt it."""
    order = order_factory(status="processing")
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff_user, amount=Decimal("40.00"), note="Adex")

    cancel_quote(quote, staff_user=staff_user, note="customer declined €40")

    quote.refresh_from_db()
    order.refresh_from_db()
    assert quote.status == "cancelled"
    assert order.status == "cancelled"
    assert "declined" in quote.note


@pytest.mark.django_db
def test_cancelling_requires_a_reason(order_factory, staff_user):
    """The note is the ONLY authorisation artifact for the manual refund wire-out. A
    customer who paid the goods total exactly produces no discrepancy, so no
    accept_discrepancy reason string exists to authorise it (see the spec)."""
    order = order_factory(status="processing")
    quote = ShippingQuote.objects.create(order=order, currency=order.currency)
    quote_freight(quote, staff_user=staff_user, amount=Decimal("40.00"), note="Adex")

    with pytest.raises(ShippingError) as exc:
        cancel_quote(quote, staff_user=staff_user, note="")

    assert exc.value.code == "reason_required"
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — `cannot import name 'cancel_quote'`.

- [ ] **Step 3: Implement**

Read `apps/orders/services.py` for `cancel_order`'s real signature first — match it, do not guess.

```python
def cancel_quote(quote, *, staff_user, note: str) -> None:
    """The customer declined the freight quote, or never answered. Silence and refusal
    are the same event operationally, so they share one terminal state distinguished by
    the note — two enum values with identical handling are a liability when the operator
    is one non-developer.

    Cancels the order and releases stock. Does NOT refund: the goods money is wired back
    by hand through the existing manual-refund endpoint. `note` + the Refund row are the
    only authorisation artifact, because a customer who paid the goods total exactly
    produced no discrepancy and so no accept_discrepancy reason exists.
    """
    from apps.orders.services import cancel_order

    if quote.is_settled:
        raise ShippingError("quote_already_settled",
                            f"This freight quote is already {quote.status}.")
    if not note.strip():
        raise ShippingError("reason_required",
                            "A reason is required — it is the record of why money is going back.")

    quote.status = "cancelled"
    quote.settled_at = timezone.now()
    _append_note(quote, f"cancelled by {staff_user.get_username()}: {note}")
    quote.save(update_fields=["status", "settled_at", "note", "updated_at"])
    cancel_order(quote.order, actor=staff_user, reason=f"freight quote cancelled: {note}")
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/shipping apps/orders -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/shipping
git commit -m "feat: cancel_quote — declined or ignored freight quote cancels the order

Silence and refusal share one terminal state. Releases stock (cosmetics have shelf
life; freeing units is what recovers value). Refund is wired by hand through the
existing endpoint — the note is the only authorisation artifact, since a customer
who paid the goods total exactly produced no discrepancy.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 10: `Order.is_shippable`

**Why:** an order whose freight is quoted-but-unpaid must not reach the ship queue. **No new `Order.status` value** — a status would touch every transition table, serializer, admin filter and status test in the codebase. A derived gate gives identical safety for a fraction of the surface.

**Files:**
- Modify: `backend/apps/orders/models.py`
- Test: `backend/apps/orders/tests/test_is_shippable.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal

import pytest

from apps.shipping.models import ShippingQuote


@pytest.mark.django_db
def test_order_with_no_quote_is_shippable(order_factory):
    """Every NG order. The gate must not change the default."""
    assert order_factory(status="processing").is_shippable is True


@pytest.mark.parametrize("status,shippable", [
    ("awaiting_quote", False), ("quoted", False),
    ("paid", True), ("waived", True), ("cancelled", True),
])
@pytest.mark.django_db
def test_unsettled_freight_blocks_shipping(order_factory, status, shippable):
    order = order_factory(status="processing")
    ShippingQuote.objects.create(
        order=order, currency=order.currency, status=status,
        amount=None if status == "awaiting_quote" else Decimal("40.00"),
    )

    order.refresh_from_db()
    assert order.is_shippable is shippable
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — `'Order' object has no attribute 'is_shippable'`.

- [ ] **Step 3: Implement**

In `backend/apps/orders/models.py`, on `Order`:

```python
    @property
    def is_shippable(self) -> bool:
        """False while freight is quoted-but-unpaid. Deliberately a derived property and
        NOT an Order.status value: a new status would touch every transition table,
        serializer, admin filter and status test in the codebase — the largest blast
        radius in this design — to say something that is entirely derivable.

        The accepted tradeoff: a ship queue written later could forget to filter on this.
        Anything that dispatches goods MUST check it.
        """
        quote = getattr(self, "shipping_quote", None)
        return quote is None or quote.is_settled
```

`shipping_quote` is the `related_name` of `ShippingQuote.order` (Task 4). `getattr` with a default is how a reverse `OneToOne` is safely probed — a bare attribute access raises `RelatedObjectDoesNotExist`.

- [ ] **Step 4: Run tests**

```bash
pytest apps/orders apps/shipping -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/orders
git commit -m "feat: Order.is_shippable — unsettled freight blocks dispatch

A derived property, not a new Order.status: a status would touch every transition
table, serializer, admin filter and status test to say something fully derivable.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: Admin endpoints + Django admin

**Files:**
- Create: `backend/apps/shipping/views.py`, `backend/apps/shipping/admin_urls.py`
- Modify: `backend/apps/shipping/admin.py`
- Modify: `backend/config/urls.py` (mount alongside `payments.admin_urls` — find how that is wired and copy it exactly)
- Test: `backend/apps/shipping/tests/test_admin_api.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
from decimal import Decimal

import pytest

from apps.shipping.models import ShippingQuote


@pytest.mark.django_db
def test_quote_endpoint(admin_client, order_factory):
    order = order_factory()
    ShippingQuote.objects.create(order=order, currency=order.currency)

    response = admin_client.post(
        f"/api/v1/admin/orders/{order.number}/freight/quote/",
        {"amount": "40.00", "note": "Adex quoted 40"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "quoted"


@pytest.mark.django_db
def test_waive_without_quote_returns_400(admin_client, order_factory):
    order = order_factory()
    ShippingQuote.objects.create(order=order, currency=order.currency)

    response = admin_client.post(
        f"/api/v1/admin/orders/{order.number}/freight/waive/",
        {"note": "goodwill"},
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json()["error"] == "quote_required_before_waive"


@pytest.mark.django_db
def test_duplicate_freight_reference_returns_409(admin_client, order_factory):
    o1, o2 = order_factory(), order_factory()
    for o in (o1, o2):
        ShippingQuote.objects.create(order=o, currency=o.currency)
        admin_client.post(f"/api/v1/admin/orders/{o.number}/freight/quote/",
                          {"amount": "40.00", "note": "Adex"}, content_type="application/json")

    body = {"amount_received": "40.00", "bank_reference": "DUP-9", "note": ""}
    first = admin_client.post(f"/api/v1/admin/orders/{o1.number}/freight/receipt/",
                              body, content_type="application/json")
    second = admin_client.post(f"/api/v1/admin/orders/{o2.number}/freight/receipt/",
                               body, content_type="application/json")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"] == "duplicate_reference"


@pytest.mark.django_db
def test_endpoints_require_staff(client, order_factory):
    order = order_factory()
    ShippingQuote.objects.create(order=order, currency=order.currency)

    response = client.post(f"/api/v1/admin/orders/{order.number}/freight/quote/",
                           {"amount": "40.00", "note": "x"}, content_type="application/json")

    assert response.status_code in (401, 403)
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL — 404 on every URL.

- [ ] **Step 3: Implement**

`backend/apps/shipping/views.py` — mirror `payments/views.py`'s structure exactly (serializer + `APIView` + `permission_classes = [permissions.IsAdminUser]  # PLAN-16: fine-grained RBAC`, the same TODO comment the other admin views carry):

```python
from decimal import Decimal

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.orders.models import Order
from apps.shipping.models import ShippingQuote
from apps.shipping.services import (
    ShippingError, cancel_quote, quote_freight, record_freight_receipt, waive_freight,
)


def _quote_payload(quote) -> dict:
    return {
        "order_number": quote.order.number,
        "status": quote.status,
        "amount": str(quote.amount) if quote.amount is not None else None,
        "currency": quote.currency_id,
        "order_status": quote.order.status,
        "is_shippable": quote.order.is_shippable,
    }


def _get_quote(number: str) -> ShippingQuote:
    order = get_object_or_404(Order, number=number)
    return get_object_or_404(ShippingQuote, order=order)


class _FreightView(APIView):
    permission_classes = [permissions.IsAdminUser]  # PLAN-16: fine-grained RBAC

    def _run(self, request, number, serializer_class, action):
        quote = _get_quote(number)
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            action(quote, staff_user=request.user, **serializer.validated_data)
        except ShippingError as exc:
            return Response({"error": exc.code, "detail": exc.detail}, status=exc.http)
        except IntegrityError:
            # The (gateway, gateway_reference) unique constraint. One transfer quoted
            # against two orders means goods ship twice against money that arrived once.
            return Response(
                {"error": "duplicate_reference",
                 "detail": "That bank reference is already recorded against a payment."},
                status=409,
            )
        quote.refresh_from_db()
        quote.order.refresh_from_db()
        return Response(_quote_payload(quote))


class QuoteSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2,
                                      min_value=Decimal("0.01"))
    note = serializers.CharField(required=False, allow_blank=True, default="")


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField()


class ReceiptSerializer(serializers.Serializer):
    amount_received = serializers.DecimalField(max_digits=12, decimal_places=2,
                                               min_value=Decimal("0.01"))
    bank_reference = serializers.CharField(max_length=128)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class QuoteFreightView(_FreightView):
    """POST /api/v1/admin/orders/{number}/freight/quote/ — record what the forwarder quoted."""

    def post(self, request, number):
        return self._run(request, number, QuoteSerializer, quote_freight)


class WaiveFreightView(_FreightView):
    """POST .../freight/waive/ — merchant absorbs the freight. Requires a prior quote."""

    def post(self, request, number):
        return self._run(request, number, NoteSerializer, waive_freight)


class CancelQuoteView(_FreightView):
    """POST .../freight/cancel/ — customer declined or never answered. Cancels the order."""

    def post(self, request, number):
        return self._run(request, number, NoteSerializer, cancel_quote)


class FreightReceiptView(_FreightView):
    """POST .../freight/receipt/ — the freight transfer landed."""

    def post(self, request, number):
        return self._run(request, number, ReceiptSerializer, record_freight_receipt)
```

`backend/apps/shipping/admin_urls.py`:

```python
from django.urls import path

from apps.shipping.views import (
    CancelQuoteView, FreightReceiptView, QuoteFreightView, WaiveFreightView,
)

urlpatterns = [
    path("orders/<str:number>/freight/quote/", QuoteFreightView.as_view()),
    path("orders/<str:number>/freight/waive/", WaiveFreightView.as_view()),
    path("orders/<str:number>/freight/cancel/", CancelQuoteView.as_view()),
    path("orders/<str:number>/freight/receipt/", FreightReceiptView.as_view()),
]
```

Mount it in `config/urls.py` under the same admin prefix as `payments.admin_urls`.

`backend/apps/shipping/admin.py` — register `ShippingQuote` with `list_display = ("order", "status", "amount", "currency", "quoted_at")`, `list_filter = ("status",)`, `search_fields = ("order__number",)`, and `readonly_fields = ("note",)`. The `note` is append-only and must never be editable by hand: an admin who can retype it can erase the trail, which is the same erasure class as Plan-09b's `_flag_review` bug. Set `list_filter` on `status` so the `awaiting_quote` work queue is one click.

- [ ] **Step 4: Run tests**

```bash
pytest apps/shipping -q
```

Expected: PASS.

- [ ] **Step 5: Full suite + ruff**

```bash
pytest -q
ruff check .
```

Expected: all green (395 pre-existing + the new tests), ruff clean. **If you see hundreds of DB errors, restart the docker stack before believing them.**

- [ ] **Step 6: Commit**

```bash
git add apps/shipping config
git commit -m "feat: admin endpoints for the freight quote lifecycle

quote / waive / cancel / receipt, mirroring the payments admin API. The append-only
note is readonly in the Django admin — an editable trail is an erasable trail.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 12: Bank-details email — OUR charges

**Why:** every RoW goods transfer arrives short (correspondent fees), routing every RoW order through `accept_discrepancy`. This does not fix that — it reduces how often it fires. A template string, not code. It will not work every time.

**Files:**
- Modify: `backend/apps/orders/templates/.../order_received.txt` and `.html` (find the real paths — Plan-09b touched them)
- Test: `backend/apps/orders/tests/` (extend the existing `order_received` test)

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_non_ngn_bank_details_email_asks_for_our_charges(...):
    """An intl wire under the default SHA terms has correspondent fees deducted in
    flight, so the customer sends 50 and 32 lands — which routes every RoW order
    through accept_discrepancy. OUR charges (sender pays all fees) is the only lever
    that does not require code."""
    # ... render order_received for a ZZ order ...
    assert "OUR" in body
    assert "all transfer charges" in body.lower()
```

Follow the existing `order_received` rendering test's structure exactly. Plan-09b's hardest lesson: **rendering the artefact found the bug; 392 green tests did not.** Render it and read the output yourself.

- [ ] **Step 2: Run to verify failure**

Expected: FAIL.

- [ ] **Step 3: Implement**

Add to both templates, conditional on the order's country **not** being the default market (an NG domestic transfer has no correspondent chain):

> **Important:** please ask your bank to send this transfer with **"OUR" charges** (you pay all transfer fees). Otherwise intermediary banks deduct their fees from the amount in transit, less than the full total reaches us, and we cannot release your order until the shortfall is resolved.

Mind the label-padding trap Plan-09b fixed in the `.txt` part: `ljust` pads *up to* a width and does not guarantee a separator, which rendered Canada's `Institution number:003` with digits flush against the colon. Do not reintroduce hand-padding.

- [ ] **Step 4: Render it and read it**

```bash
python manage.py shell
# render order_received for a ZZ order; print the text part; READ IT.
```

- [ ] **Step 5: Run tests + commit**

```bash
pytest apps/orders -q
git add apps/orders
git commit -m "feat: ask non-NG customers to send bank transfers with OUR charges

Under default SHA terms correspondent banks deduct fees in flight, so every RoW
goods transfer lands short and routes through accept_discrepancy. This reduces how
often that fires; it does not fix it.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 13: Documentation

**Files:**
- Modify: `docs/architecture.md` (repo root — **not** `backend/docs/`; Plan-09b's § "Manual payments" is there)

- [ ] **Step 1: Write § "Rest-of-World freight quotes (Plan-14a)"**

Cover:
1. **The flow:** RoW customer pays goods → `ShippingQuote(awaiting_quote)` → staff quote → customer transfers → staff record receipt → `is_shippable`.
2. **Cash-in is `sum(Payment) grouped by currency`, filtered by `purpose` when goods and freight must be told apart.** State explicitly: **never a single scalar** — NGN goods + USD freight summed is a confident wrong number.
3. **`quote.amount` is NOT cash.** It is what was asked for. `payment.amount` (purpose=freight) is what landed. They differ by correspondent fees, normally. Plan-20/28 must not treat `quote.amount` as revenue. (This mirrors Plan-09b's existing warning that `payment.amount` is not cash-in on an accepted discrepancy — the same trap, a different field.)
4. **Waived freight must appear as its own reporting line** ("freight waived: 6 orders, $340 of quoted value"). Silent waiving is the off-books hole this design closed. This is a **requirement on Plan-20**, not a nice-to-have.
5. **Plan-20's reserved-vs-sold split:** an order awaiting freight is **sold**, not reserved.
6. **The storefront contract for Plan-14:** `price: None` + `quote_required: true` ⇒ render `disclaimer`, never "Free", never "—", never arithmetic on the null. Plan-14 must carry a test.
7. **Every RoW goods payment routes through `accept_discrepancy`** — expected, documented, **not** a fraud signal. Do not widen the amount-matching tolerance to "fix" it.
8. **The freight reference is a dedup control, not an identification mechanism.** SWIFT narration gets truncated; matching is really the owner's eyes on a statement.
9. **Never auto-cancel or auto-release an order with real money against it.** No TTL on the freight wait.

- [ ] **Step 2: Update the stale cross-references**

Check `docs/architecture.md` and `master-tokerebuild.md` for claims that RoW checkout is unsupported or that delivery-currency is an open Plan-08 risk. Both are now false. Plan-09b's spec section carries an "Open question outside Plan-09b — a real Rest-of-World customer may not be able to check out at all" note: mark it **closed by Plan-14a**.

- [ ] **Step 3: Commit**

```bash
git add docs
git commit -m "docs: RoW freight quotes, cash-in rules, and the Plan-14 storefront contract

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 14: Driven end-to-end checkpoint

**Plan-09b's lesson, twice over: rendering the artefact found bugs that 392 green tests did not.** Tests are not this checkpoint.

- [ ] **Step 1: Drive it through the real HTTP endpoints against real Postgres, nothing mocked**

```bash
docker compose -f docker-compose.dev.yml up -d
```

Seed a ZZ `BankAccount` and a `quote_required` ZZ delivery option, then drive:

1. Delivery options for a **`DE`** address (never `ZZ`) → the Adex option appears with `price: null` and the disclaimer.
2. Delivery options for a **`DE`** address with an **NG** country context → **empty** (the currency block).
3. Place the order → goods-only total, `ShippingQuote(awaiting_quote)`, bank details rendered.
4. **Read the order_received email text part.** Confirm the OUR-charges paragraph, no label-padding regression.
5. Confirm the goods payment **short** (e.g. 32.00 against 40.00) → refused without `accept_discrepancy`; accepted with it + a reason. **This is the routine RoW path — confirm it feels as bad as it is.**
6. `is_shippable` is **false**.
7. Quote 40.00 → re-quote 28.00 → confirm the note still contains 40.00.
8. Record the receipt at 32.00 → `Payment(purpose="freight", amount=32.00)`, quote `paid`, `quote.amount` still 28.00.
9. `is_shippable` is **true**.
10. A second order, same `bank_reference` → **409**.
11. On a fresh order: waive without quoting → **400**; quote then waive → the forgiven amount is legible.
12. On a fresh order: cancel the quote → order `cancelled`, stock released.
13. Confirm `ConfirmManualReceiptView` still picks the **goods** payment on an order that has a freight payment.

- [ ] **Step 2: Show the owner**

Show Hammed: the `DE` options response, the rendered email, the short-payment confirm, and the freight receipt. **Do not mark this plan done without his sign-off** — Plan-09b's checkpoint is what found the Canada label bug.

- [ ] **Step 3: Merge**

```bash
git checkout main
git merge --no-ff plan-14a-row-delivery-quote
```

---

## Follow-ups — deliberately NOT built here

- **`payments.W001` cries wolf four times per deploy** (`checks.py:30` warns on every gateway's missing env vars regardless of `is_active`, while W002 correctly filters). Pre-existing, out of scope, still worth fixing — it buries W002.
- **The goods-leg duplicate-`bank_reference` TOCTOU race** (Plan-09b) is still open. The freight leg gets a real DB constraint; the goods leg still checks a JSON key unlocked. The goods leg carries most of the money. **The right fix is now visibly cheap: a `ManualReceipt` row, or move the goods reference onto the `(gateway, gateway_reference)` constraint the freight leg already uses.**
- **`_find_duplicate_reference` does an unindexed JSON scan** on every manual confirm. Fine at launch volume; needs a GIN index as the table grows.
- **Every RoW goods confirm uses `accept_discrepancy`.** The real fix is a freight-fee-aware amount policy on the goods leg, which is a payments-domain change and needs its own plan.
- **Quote history** — `note` append is the launch answer.
- **A ship queue that forgets `is_shippable`** is the accepted risk of a derived gate. Anything that dispatches goods must check it.

---

## Self-review — spec coverage

| Spec section | Task |
|---|---|
| A — RoW matching fix, resolve_country, unknown-vs-no-options, address keeps DE, region guard | 1 |
| A — delivery-currency risk (block) | 2 |
| B — `quote_required` + `disclaimer`, `price: None`, free_over suppressed | 3 |
| B — storefront contract for Plan-14 | 13 |
| C — `ShippingQuote`, row at placement, append-only note, re-quote | 4, 5, 6 |
| C — `Payment.purpose`, default `goods`, freight not via `confirm_manual_receipt` | 7, 8 |
| D — three call sites scoped; `checkout/tasks.py:52` verified unreachable | 7 |
| E — `is_shippable`, no new status | 10 |
| F — customer-facing "Awaiting shipping cost" label | **Plan-14** (no storefront exists; contract recorded in Task 13) |
| G — waive requires prior quote; loud in reporting | 6 (guard), 13 (reporting requirement on Plan-20) |
| H — currency-grouped cash-in | 13 (the aggregate itself is Plan-20's; the rule is recorded) |
| I — freight reference, real unique constraint, dedup-not-identification | 8, 13 |
| J — decline path, one terminal state, no refund flow | 9 |
| K — stock held, expiry sweep verified safe, no freight TTL, Plan-20 sold-not-reserved | 7 (verified), 13 |
| Constraint — OUR charges mitigation | 12 |
