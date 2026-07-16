# Plan-09b Manual Payments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bank transfer a complete, confirmable, refundable payment method in every market — because after the four networked gateways are deactivated it is the only one — so that money a customer actually sent becomes visible to the system and their order gets fulfilled.

**Architecture:** `bank_transfer` currently dead-ends twice. **Confirm:** `initiate()` shows bank details, then nothing can mark the order paid (`mark_paid` is reachable only via `confirm_payment` → `gateway.verify()`, which bank_transfer refuses) and the expiry sweep releases the order after 30 minutes. **Refund:** `bank_transfer.refund()` inherits a bare `NotImplementedError` that `create_refund`'s `except GatewayError` does not catch, so every refund 500s *and* wedges a `pending` Refund row that permanently reserves the amount. This plan closes both, adds per-country `BankAccount` data behind `initiate()`, and a per-gateway reservation TTL (24h for transfers). It **reuses** `confirm_payment`'s verdict ladder (extracted to `_react_to_verdict()`) and `apply_succeeded_refund` rather than forking parallel money paths.

**Tech Stack:** Django 5 + DRF, Postgres, Celery, pytest + pytest-django, factory_boy, uv, ruff.

**Branch:** `plan-09b-manual-payments`, off `plan-10-orders`. Baseline there: **328 passed, 1 skipped**.

---

## Read before Task 1

- `docs/architecture.md` §§ "Payments (Plan-09)", "Order lifecycle (Plan-10)".
- `apps/payments/services.py` — the money core. **Invariant: `payment.status == "succeeded"` is written ONLY by `_fulfil_locked`, so succeeded ⟺ fulfilled.**
- `apps/orders/state.py` — `transition()` asserts it is inside an atomic block with the row lock held and **never** auto-clears `review_reason`. `record_event` and `resolve_review` live **here**, not in `orders/services.py`.
- Emails fire via `transaction.on_commit`, never inline.

**Two facts that shape the plan:**
- The gateway is chosen at **checkout** — validated against `active_gateways_for(country)` (checkout.py:99) and the `Payment` row created (line 145) in the *same transaction* that stamps `reservation_expires_at` (line 133). So the TTL just asks the gateway; no re-stamping machinery.
- **Nothing in the codebase reads `supported_currencies`.** Not `active_gateways_for` (registry.py:32 reads only `CountryPaymentGateway`), not the payment-methods view, not checkout line 99. Do not add a `supported_currencies` property believing it gates anything — Task 3 gates in `place_order` instead.

> **This plan was adversarially reviewed by Fable 5 before coding.** Tasks 1, 6, 9, 10, 11, 12 exist or changed shape because of it. Where a step says "this ordering matters", it is because the review produced a concrete money-loss scenario for the alternative. Do not "tidy" those.

---

### Task 1: `review_reason` must append, and the verdict ladder must report its outcome

**Do this first — Task 6 is unsafe without it.**

`_flag_review` **assigns** (`services.py:126`). Today only one writer touches an order per call, so that was tolerable. Task 6 creates a second writer in the same call stack, and the collision loses money:

> Cancelled order, customer overpaid ₦12,000 against ₦10,000. `mark_paid` → `NOOP_CANCELLED` → the ladder writes *"payment received on a cancelled order — refund it"* (refund all ₦12,000; goods never ship). Task 6's overpayment branch then **overwrites** it with *"overpaid by 2,000 — refund the difference"*. Staff wire ₦2,000, resolve the flag, and the customer is out ₦10,000 with no goods and nothing left on the order recording it.

Same shape when `_reserve_and_fulfil_after_expiry` writes "could not re-reserve stock" (order NOT fulfilled, we hold the full amount) and the overpayment branch replaces it with "refund the difference".

**Files:**
- Modify: `backend/apps/payments/services.py`
- Test: `backend/apps/payments/tests/test_flag_review.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/apps/payments/tests/test_flag_review.py
import pytest

from apps.orders.state import resolve_review
from apps.payments.services import _flag_review

pytestmark = pytest.mark.django_db


def test_a_second_flag_does_not_erase_the_first(order_factory):
    # Two writers can now touch one order in a single request. An unresolved
    # "refund the whole payment" must not be silently replaced by "refund the difference".
    order = order_factory()
    _flag_review(order.pk, "payment received on a cancelled order — refund it")
    _flag_review(order.pk, "overpaid by 2000 — refund the difference")
    order.refresh_from_db()
    assert "cancelled order" in order.review_reason
    assert "overpaid by 2000" in order.review_reason


def test_the_same_reason_twice_is_not_duplicated(order_factory):
    order = order_factory()
    _flag_review(order.pk, "possible double payment")
    _flag_review(order.pk, "possible double payment")
    order.refresh_from_db()
    assert order.review_reason.count("possible double payment") == 1


def test_resolve_clears_every_accumulated_reason_in_one_act(order_factory, staff_user):
    # Plan-10's model is unchanged: an explicit admin resolve clears the flag entirely.
    order = order_factory()
    _flag_review(order.pk, "first")
    _flag_review(order.pk, "second")
    resolve_review(order.pk, actor=staff_user, message="handled both")
    order.refresh_from_db()
    assert order.review_reason == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest apps/payments/tests/test_flag_review.py -v`
Expected: FAIL — the first test's `"cancelled order"` assertion fails; the string was overwritten.

- [ ] **Step 3: Make `_flag_review` append**

Replace the body of `_flag_review` in `backend/apps/payments/services.py` (keep the existing docstring, and add the paragraph below to it):

```python
def _flag_review(order_id: int, reason: str) -> None:
    """...existing docstring...

    APPENDS rather than assigns. An order can accumulate several unresolved facts in one
    request — the ladder flags "refund the whole payment on this cancelled order" and the
    manual-receipt delta branch flags "overpaid by X" — and whichever wrote second used to
    erase the other, leaving staff acting on a partial instruction. `resolve_review` still
    clears the whole string in one explicit act, so Plan-10's model is untouched.
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        existing = [r for r in order.review_reason.split("; ") if r]
        if reason not in existing:
            existing.append(reason)
            order.review_reason = "; ".join(existing)
            order.save(update_fields=["review_reason", "updated_at"])
    logger.warning("Order %s flagged for review: %s", order_id, reason)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest apps/payments/tests/test_flag_review.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the full suite**

Run: `cd backend && uv run pytest -q`
Expected: 331 passed, 1 skipped. **Any existing test asserting `review_reason == "..."` exactly must be re-read, not blindly loosened** — confirm the change is the append semantics and not a real regression.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/payments/services.py backend/apps/payments/tests/test_flag_review.py
git commit -m "fix(payments): review_reason accumulates instead of erasing the previous flag"
```

---

### Task 2: `BankAccount` model

Replaces the three global `SiteSetting` rows (`bank_transfer.bank_name` / `.account_name` / `.account_number`) — one account for the entire world — with per-country data.

Keyed by **country, not currency**: US and ZZ both settle in USD, but a Rest-of-World customer may need SWIFT/intermediary details a domestic US customer does not, and "which account do I show this customer" is a country question. Two rows carrying the same real account number is legitimate — do **not** add a uniqueness constraint on `account_number`.

**Files:**
- Modify: `backend/apps/payments/models.py`, `backend/apps/payments/admin.py`
- Create: `backend/apps/payments/migrations/0006_bankaccount.py` (generated)
- Test: `backend/apps/payments/tests/test_bank_account.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/payments/tests/test_bank_account.py
import pytest
from django.core.exceptions import ValidationError

from apps.core.models import Country, Currency
from apps.payments.models import BankAccount

pytestmark = pytest.mark.django_db


def _account(country, **kw):
    defaults = dict(
        country=country, currency=country.currency, bank_name="GTBank",
        account_name="Toke Cosmetics Ltd", account_number="0123456789",
    )
    return BankAccount(**{**defaults, **kw})


def test_currency_must_match_the_countrys_currency():
    # A GBP account under Nigeria would show a Lagos customer an account they cannot pay
    # into in NGN. The order's currency comes from its country, so these must agree.
    account = _account(Country.objects.get(code="NG"), currency=Currency.objects.get(code="GBP"))
    with pytest.raises(ValidationError) as exc:
        account.full_clean()
    assert "currency" in exc.value.error_dict


def test_matching_currency_is_accepted():
    ng = Country.objects.get(code="NG")
    account = _account(ng)
    account.full_clean()
    account.save()
    assert ng.bank_account == account
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest apps/payments/tests/test_bank_account.py -v`
Expected: FAIL — `ImportError: cannot import name 'BankAccount'`

- [ ] **Step 3: Write the model**

Append to `backend/apps/payments/models.py` (ensure `from django.core.exceptions import ValidationError` is imported):

```python
class BankAccount(models.Model):
    """The merchant's bank account for one market. Bank transfer is the only live payment
    method at launch, so this row IS the payment page for that country — an absent or
    inactive row must make initiate() fail loudly rather than render blanks."""

    country = models.OneToOneField(
        "core.Country", on_delete=models.PROTECT, related_name="bank_account"
    )
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    bank_name = models.CharField(max_length=120)
    account_name = models.CharField(max_length=120)
    account_number = models.CharField(max_length=64)  # or IBAN
    # Per-market shape: sort_code (GB), routing_number (US), IBAN/SWIFT (intl wires).
    # A JSON blob rather than columns — every market wants a different subset and this is
    # display-only data the customer copies into their banking app. Keys are rendered
    # verbatim to the customer (see the order_received template), so write them readably.
    extra = models.JSONField(default=dict, blank=True)
    instructions = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.country_id}: {self.bank_name} {self.account_number}"

    def clean(self):
        if self.currency_id and self.country_id and self.currency_id != self.country.currency_id:
            raise ValidationError(
                {"currency": f"must be {self.country.currency_id} to match {self.country_id}"}
            )
```

- [ ] **Step 4: Generate and apply the migration**

Run: `cd backend && uv run python manage.py makemigrations payments -n bankaccount && uv run python manage.py migrate`
Expected: `0006_bankaccount.py` created and applied.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest apps/payments/tests/test_bank_account.py -v`
Expected: 2 passed

- [ ] **Step 6: Register in Django admin**

Django admin is the launch-time CRUD — Plan-18 owns the real admin UI; do **not** build a screen here.

```python
# backend/apps/payments/admin.py
@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("country", "currency", "bank_name", "account_number", "is_active")
    list_filter = ("is_active", "country")
```

- [ ] **Step 7: Commit**

```bash
git add backend/apps/payments/models.py backend/apps/payments/migrations/0006_bankaccount.py backend/apps/payments/admin.py backend/apps/payments/tests/test_bank_account.py
git commit -m "feat(payments): per-country BankAccount model"
```

---

### Task 3: Gateway class attributes — `confirmation` and `reservation_ttl_minutes`

`confirmation` replaces inferring manual-ness from `InitiateResult.action == "bank_details"` **for the TTL and confirm questions only**. Note `_initiate_payment` (checkout.py:173) keys the `order_received` email off `action == "bank_details"` and that stays — "did the customer leave checkout holding instructions" genuinely is an action-shaped question. Two adjacent concepts, two different questions; Task 14's docs must say which is which so nobody "unifies" them.

`reservation_ttl_minutes` is a **property** on the ABC, not a class-body constant: `= settings.RESERVATION_TTL_MINUTES` in a class body freezes at import, so `override_settings` cannot move it and changing the env var needs a restart.

**Files:**
- Modify: `backend/apps/payments/gateways/base.py`, `backend/apps/payments/gateways/bank_transfer.py`
- Test: `backend/apps/payments/tests/test_gateway_contract.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/payments/tests/test_gateway_contract.py
import pytest
from django.test import override_settings

from apps.payments.gateways.registry import _REGISTRY, get_gateway


def test_only_bank_transfer_is_manually_confirmed():
    manual = {code for code, g in _REGISTRY.items() if g.confirmation == "manual"}
    assert manual == {"bank_transfer"}


@override_settings(RESERVATION_TTL_MINUTES=17)
def test_networked_gateways_follow_the_setting_at_call_time():
    # A class-body `= settings.X` would freeze at import and ignore this.
    assert get_gateway("paystack").reservation_ttl_minutes == 17


@override_settings(RESERVATION_TTL_MINUTES=17)
def test_bank_transfer_holds_stock_for_24_hours_regardless():
    # A transfer waits on staff working hours; 30 minutes would expire every order before
    # the money could possibly be confirmed. Not tunable by the card setting.
    assert get_gateway("bank_transfer").reservation_ttl_minutes == 1440
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest apps/payments/tests/test_gateway_contract.py -v`
Expected: FAIL — `AttributeError: 'PaystackGateway' object has no attribute 'confirmation'`

- [ ] **Step 3: Write the implementation**

In `backend/apps/payments/gateways/base.py` (add `from django.conf import settings`):

```python
class PaymentGateway(ABC):
    code: str
    supported_currencies: set[str]

    # How does money become confirmed for this gateway?
    #   "gateway" — ask it over the network (verify()); the default for anything networked.
    #   "manual"  — a human reads a bank statement; there is no machine to ask.
    # Deliberately NOT inferred from InitiateResult.action: that bit answers "did the
    # customer leave holding instructions" (which is why the order_received email keys off
    # it and should keep doing so), a different question from "can this be verify()'d" —
    # a future Paystack dedicated account is not instant but IS machine-confirmable.
    confirmation: str = "gateway"

    @property
    def reservation_ttl_minutes(self) -> int:
        """How long checkout holds the stock reservation for an order paying via this
        gateway. A property, not a class attribute: `= settings.RESERVATION_TTL_MINUTES`
        in the class body is evaluated at import and would ignore override_settings and
        any env change without a restart. Subclasses shadow it with a plain int."""
        return settings.RESERVATION_TTL_MINUTES
```

In `backend/apps/payments/gateways/bank_transfer.py`, on `BankTransferGateway` (a plain class attribute correctly shadows the base property via the MRO):

```python
    confirmation = "manual"
    reservation_ttl_minutes = 1440  # 24h — NG transfers are NIP-instant; the delay is staff hours
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest apps/payments/tests/test_gateway_contract.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/payments/gateways/base.py backend/apps/payments/gateways/bank_transfer.py backend/apps/payments/tests/test_gateway_contract.py
git commit -m "feat(payments): gateways declare confirmation mode and reservation TTL"
```

---

### Task 4: `initiate()` reads `BankAccount`; checkout refuses before reserving stock

Two failures to close:

1. `SiteSetting.get_typed("bank_transfer.account_number", "")` defaults to `""` — an unconfigured market renders a payment page with an **empty account number** and the customer wires into nowhere.
2. Gating at `initiate()` alone is **too late**. `place_order` phase 1 commits (order created, stock reserved **for 24h**, cart flipped to `converted`) and only then does phase 2 call `initiate()` and 503. The customer retries and burns another 24h stock hold per attempt. The check belongs in phase 1, beside the existing line-99 gateway validation.

**Do not** add a `supported_currencies` property to do this gating — nothing reads that attribute (see "Read before Task 1"). Delete the hardcoded `{"NGN"}` and leave it at that.

**Files:**
- Modify: `backend/apps/payments/gateways/bank_transfer.py`, `backend/apps/checkout/services/checkout.py`
- Delete: `backend/apps/payments/management/commands/seed_bank_transfer_demo.py`
- Test: `backend/apps/payments/tests/test_bank_transfer_gateway.py`, `backend/apps/checkout/tests/test_checkout_bank_account.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/apps/payments/tests/test_bank_transfer_gateway.py
import pytest

from apps.core.models import Country
from apps.payments.gateways.base import GatewayNotConfigured
from apps.payments.gateways.registry import get_gateway
from apps.payments.models import BankAccount

pytestmark = pytest.mark.django_db


def _make_account(code, **kw):
    country = Country.objects.get(code=code)
    defaults = dict(
        country=country, currency=country.currency, bank_name=f"{code} Bank",
        account_name="Toke Cosmetics Ltd", account_number=f"{code}-0001",
    )
    return BankAccount.objects.create(**{**defaults, **kw})


def test_initiate_returns_the_account_for_the_orders_country(order_factory):
    _make_account("NG")
    _make_account("GB", extra={"sort_code": "04-00-04"})
    order = order_factory(country=Country.objects.get(code="GB"))
    result = get_gateway("bank_transfer").initiate(order.payments.first(), order)
    assert result.action == "bank_details"
    assert result.data["account_number"] == "GB-0001"      # NOT the NG account
    assert result.data["sort_code"] == "04-00-04"          # per-market field carried through


def test_initiate_refuses_when_the_country_has_no_account(order_factory):
    order = order_factory(country=Country.objects.get(code="CA"))
    with pytest.raises(GatewayNotConfigured):
        get_gateway("bank_transfer").initiate(order.payments.first(), order)


def test_initiate_refuses_when_the_account_is_deactivated(order_factory):
    _make_account("NG", is_active=False)
    order = order_factory(country=Country.objects.get(code="NG"))
    # Never render a blank account number — the customer would wire into nowhere.
    with pytest.raises(GatewayNotConfigured):
        get_gateway("bank_transfer").initiate(order.payments.first(), order)
```

```python
# backend/apps/checkout/tests/test_checkout_bank_account.py
import pytest

from apps.checkout.services.checkout import CheckoutError, place_order
from apps.orders.models import Order

pytestmark = pytest.mark.django_db


def test_checkout_refuses_before_reserving_stock_when_no_account_exists(ca_cart_ctx):
    # Failing only at initiate() (phase 2) would leave an order holding stock for 24h and
    # a converted cart behind, and every retry would burn another 24h hold.
    before = Order.objects.count()
    with pytest.raises(CheckoutError) as exc:
        place_order(**ca_cart_ctx, payment_gateway="bank_transfer")
    assert exc.value.code == "gateway_unavailable"
    assert Order.objects.count() == before
    assert ca_cart_ctx["cart"].status == "active"   # cart not consumed
```

> **Implementer note:** `ca_cart_ctx` is a fixture giving a live CA cart/address context with `bank_transfer` active for CA and **no** `BankAccount`. Follow the existing checkout test fixtures. Match `CheckoutError`'s real constructor/attribute names (`code`, `http`) — read `checkout.py` rather than trusting this snippet.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest apps/payments/tests/test_bank_transfer_gateway.py apps/checkout/tests/test_checkout_bank_account.py -v`
Expected: FAIL — gateway tests read the global SiteSetting / return blanks; the checkout test creates an order and then 503s from phase 2.

- [ ] **Step 3: Rewrite the gateway**

Replace `backend/apps/payments/gateways/bank_transfer.py`:

```python
from apps.payments.gateways.base import (
    GatewayNotConfigured,
    InitiateResult,
    ManualVerificationOnly,
    PaymentGateway,
)


class BankTransferGateway(PaymentGateway):
    """Manual bank transfer — the ONLY live method at launch (see Plan-09b). No external
    HTTP: initiate() returns the merchant's bank details for the order's country and the
    order sits pending_payment until a staff member confirms receipt against the bank
    statement (payments.services.confirm_manual_receipt). Payment stays 'initiated'."""

    code = "bank_transfer"
    confirmation = "manual"
    reservation_ttl_minutes = 1440

    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        from apps.payments.models import BankAccount  # lazy: registry imports this module

        account = BankAccount.objects.filter(country=order.country, is_active=True).first()
        if account is None:
            # Fail loudly. The old SiteSetting lookup defaulted to "" and would render a
            # payment page with an empty account number — the customer wires into nowhere
            # and that money is genuinely unrecoverable. Checkout gates on this too, so
            # reaching here means the account was deactivated mid-checkout.
            raise GatewayNotConfigured(
                f"no active BankAccount for {order.country_id} — cannot show bank details"
            )
        return InitiateResult(
            action="bank_details",
            reference=order.number,
            data={
                "bank_name": account.bank_name,
                "account_name": account.account_name,
                "account_number": account.account_number,
                **account.extra,
                "amount": str(order.grand_total),
                "currency": order.currency_id,
                "reference": order.number,
                "instructions": account.instructions
                or "Use your order number as the transfer reference.",
            },
        )

    def verify(self, payment):
        """There is no machine to ask — the staff member reading the bank statement IS the
        verification (see confirm_manual_receipt). Declining in the gateway vocabulary
        rather than inheriting the base NotImplementedError is what keeps the customer's
        "check my payment" button returning their order status instead of a 500."""
        raise ManualVerificationOnly(
            "bank_transfer is confirmed by a human, not by the gateway"
        )
```

Note `supported_currencies` is simply gone. It is unreachable dead weight either way; leaving the hardcoded `{"NGN"}` would be an active lie.

- [ ] **Step 4: Gate in checkout phase 1**

In `backend/apps/checkout/services/checkout.py`, immediately after the line-99 gateway-active check:

```python
        # A manual gateway needs a configured account BEFORE we reserve stock. Failing at
        # initiate() (phase 2, post-commit) would leave an order holding stock for the full
        # 24h TTL and a converted cart, and every retry would burn another hold.
        gateway = get_gateway(payment_gateway)
        if gateway.confirmation == "manual":
            from apps.payments.models import BankAccount

            if not BankAccount.objects.filter(country=country, is_active=True).exists():
                raise CheckoutError(
                    "gateway_unavailable", "Payment method not available.", http=400
                )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest apps/payments/tests/test_bank_transfer_gateway.py apps/checkout/tests/test_checkout_bank_account.py -v`
Expected: 4 passed

- [ ] **Step 6: Delete the dead demo seeder**

The `bank_transfer.*` SiteSettings no longer feed anything.

Run: `git rm backend/apps/payments/management/commands/seed_bank_transfer_demo.py && cd backend && uv run pytest -q`
Expected: any failure is a test seeding the old SiteSettings — port it to `BankAccount.objects.create(...)`.

- [ ] **Step 7: Commit**

```bash
git add -A backend/apps/payments/ backend/apps/checkout/
git commit -m "fix(payments): bank details come from the country's account, never blanks"
```

---

### Task 5: Per-gateway reservation TTL at checkout

**Files:**
- Modify: `backend/apps/checkout/services/checkout.py:133`
- Test: `backend/apps/checkout/tests/test_checkout_ttl.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/checkout/tests/test_checkout_ttl.py
import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def test_bank_transfer_order_holds_stock_for_24_hours(place_order_via):
    # 30 minutes (the card default) would expire this order before the money could land.
    order = place_order_via("bank_transfer")
    held = (order.reservation_expires_at - timezone.now()).total_seconds()
    assert 23.5 * 3600 < held < 24.5 * 3600


def test_card_order_still_holds_stock_for_30_minutes(place_order_via):
    order = place_order_via("paystack")
    held = (order.reservation_expires_at - timezone.now()).total_seconds()
    assert 25 * 60 < held < 35 * 60
```

> **Implementer note:** `place_order_via(gateway_code)` is a fixture in `apps/checkout/tests/conftest.py`: activate that gateway for the country via `CountryPaymentGateway`, seed a `BankAccount` for the bank_transfer case, call `place_order`. Reuse the existing checkout fixtures.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest apps/checkout/tests/test_checkout_ttl.py -v`
Expected: FAIL — the bank_transfer test sees ~30 minutes.

- [ ] **Step 3: Write the implementation**

In `backend/apps/checkout/services/checkout.py`, replace line 133:

```python
            reservation_expires_at=timezone.now() + timedelta(minutes=settings.RESERVATION_TTL_MINUTES),
```

with (reusing the `gateway` local from Task 4's check):

```python
            # Per-gateway: a card resolves in seconds, a bank transfer waits on staff
            # working hours. The gateway is already known and validated here, and its
            # Payment row is created in this same transaction, so nothing needs
            # re-stamping at initiate time.
            reservation_expires_at=timezone.now()
            + timedelta(minutes=gateway.reservation_ttl_minutes),
```

`RESERVATION_TTL_MINUTES` keeps its meaning — it is what the ABC's property returns, so it now tunes card gateways.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest apps/checkout/tests/test_checkout_ttl.py apps/payments/tests/test_gateway_contract.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/checkout/services/checkout.py backend/apps/checkout/tests/test_checkout_ttl.py
git commit -m "feat(checkout): reservation TTL comes from the chosen gateway"
```

---

### Task 6: Extract `_react_to_verdict`, returning the FINAL outcome

Pure refactor plus one addition: the ladder must **report what actually happened**, because Task 7 may only write a delta flag when the order really got fulfilled (Task 1's scenario). `NOOP_EXPIRED` is the subtle one — `_reserve_and_fulfil_after_expiry` may fulfil (re-reserve succeeded) **or** not (stock gone). The input verdict cannot tell you; the return value must.

**Files:**
- Modify: `backend/apps/payments/services.py`
- Test: existing `backend/apps/payments/tests/` must stay green, plus one new test

- [ ] **Step 1: Capture the green baseline**

Run: `cd backend && uv run pytest apps/payments -q`
Expected: all pass. Record the count.

- [ ] **Step 2: Write the failing test**

```python
# backend/apps/payments/tests/test_react_to_verdict.py
import pytest

from apps.payments.services import MarkPaidResult, _react_to_verdict, mark_paid

pytestmark = pytest.mark.django_db


def test_reports_fulfilled_when_the_order_is_fulfilled(bank_transfer_order):
    _, payment = bank_transfer_order
    assert _react_to_verdict(payment, mark_paid(payment)) is True


def test_reports_not_fulfilled_when_late_payment_cannot_re_reserve(expired_order_no_stock):
    # The order stays `expired` and we hold the customer's money — the ladder's own flag
    # ("could not re-reserve stock") is the operative instruction and must not be
    # overwritten by a delta flag that assumes fulfilment.
    _, payment = expired_order_no_stock
    assert _react_to_verdict(payment, MarkPaidResult.NOOP_EXPIRED) is False


def test_reports_not_fulfilled_on_a_cancelled_order(cancelled_order_with_payment):
    _, payment = cancelled_order_with_payment
    assert _react_to_verdict(payment, MarkPaidResult.NOOP_CANCELLED) is False
```

- [ ] **Step 3: Extract the ladder**

In `backend/apps/payments/services.py`, add above `confirm_payment` and replace `confirm_payment`'s tail with a call:

```python
def _react_to_verdict(payment, outcome: MarkPaidResult) -> bool:
    """React to mark_paid's verdict. Returns whether the order ended up FULFILLED.

    Shared by BOTH confirmation paths (gateway verify and manual receipt) — the recovery
    logic for late/cancelled/duplicate money is identical regardless of who did the
    verifying, and a copy-paste would let one path silently stop recovering money.

    The return value matters: NOOP_EXPIRED may or may not end in fulfilment depending on
    whether _reserve_and_fulfil_after_expiry could re-reserve stock, and callers that flag
    an amount discrepancy must only do so when the goods actually shipped — otherwise they
    overwrite the ladder's own, more urgent, instruction (see _flag_review's docstring).
    """
    if outcome is MarkPaidResult.FULFILLED:
        return True

    if outcome is MarkPaidResult.NOOP_EXPIRED:
        _reserve_and_fulfil_after_expiry(payment.order, payment)
        payment.refresh_from_db(fields=["status"])
        return payment.status == "succeeded"  # succeeded <=> fulfilled, by invariant

    if outcome is MarkPaidResult.NOOP_CANCELLED:
        _flag_review(
            payment.order_id,
            f"payment {payment.pk} received on a cancelled order — refund it",
        )
        return False

    # NOOP_ALREADY_PROCESSED: either an idempotent replay of THIS payment, or a second,
    # distinct payment for an order another payment already fulfilled (double charge).
    payment.refresh_from_db(fields=["status"])
    if payment.status == "succeeded":
        return True  # this payment already fulfilled the order — benign replay
    _flag_review(
        payment.order_id,
        f"possible double payment — order already processing; refund payment {payment.pk}",
    )
    return False
```

Then in `confirm_payment`, replace everything from `outcome = mark_paid(payment)` to the end with:

```python
    _react_to_verdict(payment, mark_paid(payment))
```

- [ ] **Step 4: Verify nothing else changed**

Run: `cd backend && uv run pytest apps/payments -q`
Expected: the Step 1 count plus 3. **A behaviour change in the existing tests is a bug in the refactor** — revert and redo.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/payments/services.py backend/apps/payments/tests/test_react_to_verdict.py
git commit -m "refactor(payments): the verdict ladder is shared and reports its outcome"
```

---

### Task 7: `confirm_manual_receipt()` — the service that makes the money visible

The heart of the plan. Skips `verify()`; the staff-entered amount replaces the gateway-reported one.

**Any nonzero delta requires an explicit boolean.** The merchant's decision (overpayment fulfils) stands, but a **staff typo is the expensive failure**: `50000` for `5000` would fulfil *and* plant a flag authorising a human to wire ₦45,000 out — and with refunds manual (Task 12) that flag *is* the authorisation; no gateway ledger will refuse it. So an unexpected amount fails loudly with the computed delta and the caller must come back explicitly. That the 400 carries `expected`/`received` gives Plan-18's "are you sure?" for free.

Ordering that matters (do not tidy):
- `record_event` fires **after** `mark_paid`, with the outcome in the message. Before it, a losing racer writes a "confirmed" event for a confirmation that did nothing.
- Delta flags fire **only when `_react_to_verdict` returned True**. Otherwise the ladder's flag is the operative one (Task 1).
- `raw_response["manual_receipt"]` is keyed **by bank reference**, not overwritten — two unlocked saves are last-write-wins, and a losing racer would otherwise replace the winning receipt with an amount that fulfilled nothing.

**Files:**
- Modify: `backend/apps/payments/services.py`
- Test: `backend/apps/payments/tests/test_confirm_manual_receipt.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/apps/payments/tests/test_confirm_manual_receipt.py
from decimal import Decimal

import pytest

from apps.payments.services import (
    AmountDiscrepancy,
    DuplicateBankReference,
    confirm_manual_receipt,
)

pytestmark = pytest.mark.django_db


def test_exact_amount_fulfils(bank_transfer_order, staff_user):
    order, payment = bank_transfer_order          # grand_total = 10000 NGN
    confirm_manual_receipt(payment, staff_user=staff_user,
                           amount_received=Decimal("10000.00"), bank_reference="FT001")
    order.refresh_from_db(); payment.refresh_from_db()
    assert order.status == "processing"
    assert payment.status == "succeeded"
    assert order.review_reason == ""


def test_an_unexpected_amount_fails_loudly_instead_of_fulfilling(bank_transfer_order, staff_user):
    # The staff-typo guard: 50000 for 5000 must not fulfil AND authorise a 45k wire-out.
    order, payment = bank_transfer_order
    with pytest.raises(AmountDiscrepancy) as exc:
        confirm_manual_receipt(payment, staff_user=staff_user,
                               amount_received=Decimal("50000.00"), bank_reference="FT002")
    assert exc.value.expected == Decimal("10000.00")
    assert exc.value.received == Decimal("50000.00")
    order.refresh_from_db(); payment.refresh_from_db()
    assert order.status == "pending_payment"
    assert payment.status != "succeeded"
    # A refused attempt did nothing — the caller already got the numbers. Audit it, but
    # do NOT leave a review flag behind for an event that never happened.
    assert order.review_reason == ""
    assert order.events.filter(type="manual_receipt_refused").exists()


def test_overpayment_fulfils_and_flags_when_explicitly_accepted(bank_transfer_order, staff_user):
    order, payment = bank_transfer_order
    confirm_manual_receipt(payment, staff_user=staff_user,
                           amount_received=Decimal("12000.00"), bank_reference="FT003",
                           accept_discrepancy=True, note="customer sent extra by mistake")
    order.refresh_from_db()
    assert order.status == "processing"
    assert "2000" in order.review_reason and "refund" in order.review_reason.lower()


def test_underpayment_does_not_fulfil_even_when_accepted_is_false(bank_transfer_order, staff_user):
    order, payment = bank_transfer_order
    with pytest.raises(AmountDiscrepancy):
        confirm_manual_receipt(payment, staff_user=staff_user,
                               amount_received=Decimal("6000.00"), bank_reference="FT004")
    order.refresh_from_db(); payment.refresh_from_db()
    assert order.status == "pending_payment"
    assert payment.status != "succeeded"     # invariant: succeeded <=> fulfilled


def test_accepted_shortfall_fulfils_and_records_who_accepted_it(bank_transfer_order, staff_user):
    # The intl-wire case: intermediary banks eat a slice, so the amount ARRIVING is
    # legitimately less than the amount sent. A human decides — never a tolerance band.
    order, payment = bank_transfer_order
    confirm_manual_receipt(payment, staff_user=staff_user,
                           amount_received=Decimal("9982.00"), bank_reference="FT005",
                           accept_discrepancy=True, note="intermediary bank fee")
    order.refresh_from_db()
    assert order.status == "processing"
    assert "18" in order.review_reason


def test_accepting_a_discrepancy_requires_a_reason(bank_transfer_order, staff_user):
    # The anti-"staff always tick the box" control: mandatory friction, and it lands in
    # the audit trail.
    order, payment = bank_transfer_order
    with pytest.raises(ValueError, match="reason"):
        confirm_manual_receipt(payment, staff_user=staff_user,
                               amount_received=Decimal("9982.00"), bank_reference="FT006",
                               accept_discrepancy=True, note="   ")
    order.refresh_from_db()
    assert order.status == "pending_payment"


def test_one_statement_line_cannot_release_two_orders(two_bank_transfer_orders, staff_user):
    # Customer sends ONE transfer and quotes the same reference for two orders. Without
    # this, goods ship twice against money that arrived once.
    (o1, p1), (o2, p2) = two_bank_transfer_orders
    confirm_manual_receipt(p1, staff_user=staff_user,
                           amount_received=Decimal("10000.00"), bank_reference="FT-DUP")
    with pytest.raises(DuplicateBankReference) as exc:
        confirm_manual_receipt(p2, staff_user=staff_user,
                               amount_received=Decimal("10000.00"), bank_reference="FT-DUP")
    assert o1.number in str(exc.value)
    o2.refresh_from_db()
    assert o2.status == "pending_payment"


def test_confirming_twice_is_a_benign_noop_not_a_double_payment_flag(bank_transfer_order, staff_user):
    # Two staff confirming one transfer is one human being slow, NOT two charges.
    order, payment = bank_transfer_order
    confirm_manual_receipt(payment, staff_user=staff_user,
                           amount_received=Decimal("10000.00"), bank_reference="FT007")
    confirm_manual_receipt(payment, staff_user=staff_user,
                           amount_received=Decimal("10000.00"), bank_reference="FT007",
                           allow_duplicate_reference=True)
    order.refresh_from_db()
    assert order.status == "processing"
    assert "double payment" not in order.review_reason


def test_records_who_confirmed_and_against_which_statement_line(bank_transfer_order, staff_user):
    order, payment = bank_transfer_order
    confirm_manual_receipt(payment, staff_user=staff_user,
                           amount_received=Decimal("10000.00"), bank_reference="FT008",
                           note="seen on GTBank statement")
    event = order.events.get(type="payment_confirmed_manually")
    assert event.actor == staff_user
    assert "FT008" in event.message and "10000" in event.message


def test_a_networked_gateway_cannot_be_hand_waved_into_succeeded(paystack_order, staff_user):
    order, payment = paystack_order
    with pytest.raises(ValueError, match="machine-confirmed"):
        confirm_manual_receipt(payment, staff_user=staff_user,
                               amount_received=Decimal("10000.00"), bank_reference="X")
```

> **Implementer note:** fixtures needed in `apps/payments/tests/conftest.py`: `bank_transfer_order` → `(order, payment)`, `pending_payment`, `grand_total = Decimal("10000.00")` NGN, live NG `BankAccount`, valid reservation under `order.reservation_reference`, `Payment(gateway="bank_transfer", status="initiated")`. Plus `two_bank_transfer_orders`, `paystack_order`, `expired_order_no_stock`, `cancelled_order_with_payment`, `staff_user`, `customer_user`. Build them on the existing factories; if that is awkward, fix the factories rather than duplicating setup across six test files.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest apps/payments/tests/test_confirm_manual_receipt.py -v`
Expected: FAIL — `ImportError: cannot import name 'confirm_manual_receipt'`

- [ ] **Step 3: Write the implementation**

Add to `backend/apps/payments/services.py` (add `from decimal import Decimal` and `from apps.payments.money import from_minor, to_minor` at the top; keep `get_gateway` imported **lazily inside functions**, as `confirm_payment` already does — registry → bank_transfer → `payments.models` is a live cycle risk):

```python
class AmountDiscrepancy(Exception):
    """The confirmed amount is not the order total and staff did not explicitly accept it.
    Nothing was fulfilled. Carries the numbers so the caller can show them and come back."""

    def __init__(self, expected: Decimal, received: Decimal):
        self.expected, self.received = expected, received
        super().__init__(f"received {received}, order is owed {expected}")


class DuplicateBankReference(Exception):
    """This bank reference already confirmed another order — one statement line cannot pay
    for two orders. Override with allow_duplicate_reference=True."""


def _find_duplicate_reference(payment, bank_reference: str):
    """Another payment already confirmed against this statement line, if any. The cheapest
    fraud control we have: one transfer quoted as the reference for two orders would
    otherwise ship goods twice against money that arrived once."""
    return (
        Payment.objects.filter(
            gateway=payment.gateway,
            raw_response__manual_receipt__has_key=bank_reference,
        )
        .exclude(pk=payment.pk)
        .select_related("order")
        .first()
    )


def confirm_manual_receipt(
    payment,
    *,
    staff_user,
    amount_received: Decimal,
    bank_reference: str,
    note: str = "",
    accept_discrepancy: bool = False,
    allow_duplicate_reference: bool = False,
) -> None:
    """Fulfil an order whose money arrived by bank transfer. The staff member reading the
    bank statement IS the verification — there is no gateway to ask — so this deliberately
    does NOT call verify(). It reuses mark_paid and the shared verdict ladder, because the
    recovery logic for late/cancelled/duplicate money doesn't care who did the verifying.

    Any nonzero delta requires accept_discrepancy + a reason. Overpayment then fulfils and
    flags the surplus for refund (they paid enough — don't hold their goods hostage);
    shortfall then fulfils and records who accepted it (intl wires legitimately lose a
    slice to intermediary banks). Without the flag an unexpected amount raises, because the
    common cause is a typo and the resulting flag is the ONLY authorisation a human needs
    to wire real money out.
    """
    from apps.orders.state import record_event
    from apps.payments.gateways.registry import get_gateway

    if get_gateway(payment.gateway).confirmation != "manual":
        # Letting staff hand-wave a Stripe payment into 'succeeded' would break
        # succeeded <=> money-actually-arrived.
        raise ValueError(
            f"{payment.gateway} is machine-confirmed — use confirm_payment(), not manual receipt"
        )

    expected_minor = to_minor(payment.amount, payment.currency)
    received_minor = to_minor(amount_received, payment.currency)
    delta = received_minor - expected_minor

    if delta and not accept_discrepancy:
        record_event(
            payment.order, "manual_receipt_refused", actor=staff_user,
            message=(
                f"refused: {amount_received} {payment.currency_id} against "
                f"{payment.amount} (ref {bank_reference})"
            ),
        )
        # Deliberately NO review flag: nothing happened, and the caller already has the
        # numbers. A flag here would outlive the corrected confirm that follows.
        raise AmountDiscrepancy(payment.amount, amount_received)

    if delta and not note.strip():
        raise ValueError("accepting an amount discrepancy requires a reason")

    if not allow_duplicate_reference:
        other = _find_duplicate_reference(payment, bank_reference)
        if other is not None:
            raise DuplicateBankReference(
                f"bank reference {bank_reference} already confirmed order {other.order.number}"
            )

    # Keyed by reference rather than replaced: two staff confirming concurrently both save
    # here unlocked, and last-write-wins would leave the payment recording an amount that
    # fulfilled nothing. The OrderEvents are the audit trail; this is the ledger detail.
    receipts = dict((payment.raw_response or {}).get("manual_receipt", {}))
    receipts[bank_reference] = {
        "amount_received": str(amount_received),
        "confirmed_by": staff_user.get_username(),
        "note": note,
        "accept_discrepancy": accept_discrepancy,
    }
    payment.raw_response = {**(payment.raw_response or {}), "manual_receipt": receipts}
    payment.save(update_fields=["raw_response", "updated_at"])

    fulfilled = _react_to_verdict(payment, mark_paid(payment))

    # AFTER mark_paid, with the outcome: recording "confirmed" before it would have a
    # losing racer claim credit for a confirmation that did nothing.
    record_event(
        payment.order, "payment_confirmed_manually", actor=staff_user,
        message=(
            f"{amount_received} {payment.currency_id} confirmed against bank reference "
            f"{bank_reference} — {'fulfilled' if fulfilled else 'no fulfilment (see flags)'}"
            + (f" — {note}" if note else "")
        ),
    )

    if not fulfilled:
        # The ladder already flagged the operative instruction (refund it / could not
        # re-reserve). A delta flag here would append noise to an unresolved, more urgent
        # fact — or worse, imply the goods shipped.
        return

    if delta > 0:
        _flag_review(
            payment.order_id,
            f"overpaid by {from_minor(delta, payment.currency)} {payment.currency_id} "
            f"(received {amount_received} against {payment.amount}) — refund the difference",
        )
    elif delta < 0:
        _flag_review(
            payment.order_id,
            f"shortfall of {from_minor(-delta, payment.currency)} {payment.currency_id} "
            f"accepted by {staff_user.get_username()}: {note} "
            f"(received {amount_received} against {payment.amount})",
        )
```

> If `from_minor` does not exist in `money.py`, add it as the inverse of `to_minor` (integer minor units → `Decimal` major, off `Currency.decimal_places`) with its own unit test. Do not hand-roll the division at the call site.
>
> `raw_response__manual_receipt__has_key` requires the JSONField lookup to hit an object keyed by reference — which is why the shape above is a dict, not a list. Verify the query on Postgres; add an index if the payments table grows (it will not before Plan-21).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest apps/payments/tests/test_confirm_manual_receipt.py -v`
Expected: 10 passed

- [ ] **Step 5: Full payments suite**

Run: `cd backend && uv run pytest apps/payments -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/payments/services.py backend/apps/payments/tests/
git commit -m "feat(payments): confirm_manual_receipt — staff confirm bank transfers"
```

---

### Task 8: Admin confirm-receipt API

**Files:**
- Modify: `backend/apps/payments/views.py`, `backend/apps/payments/admin_urls.py`
- Test: `backend/apps/payments/tests/test_admin_confirm_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/apps/payments/tests/test_admin_confirm_api.py
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _url(order):
    return f"/api/v1/admin/orders/{order.number}/confirm-payment/"


def test_staff_can_confirm_receipt(bank_transfer_order, staff_user):
    order, _ = bank_transfer_order
    client = APIClient(); client.force_authenticate(staff_user)
    resp = client.post(_url(order), {"amount_received": "10000.00",
                                     "bank_reference": "FT001"}, format="json")
    assert resp.status_code == 200
    order.refresh_from_db()
    assert order.status == "processing"


def test_customers_cannot_confirm_their_own_payment(bank_transfer_order, customer_user):
    order, _ = bank_transfer_order
    client = APIClient(); client.force_authenticate(customer_user)
    resp = client.post(_url(order), {"amount_received": "10000.00",
                                     "bank_reference": "FT001"}, format="json")
    assert resp.status_code == 403
    order.refresh_from_db()
    assert order.status == "pending_payment"


def test_a_discrepancy_returns_400_with_the_numbers(bank_transfer_order, staff_user):
    # The UI's "are you sure?" is built from this response.
    order, _ = bank_transfer_order
    client = APIClient(); client.force_authenticate(staff_user)
    resp = client.post(_url(order), {"amount_received": "6000.00",
                                     "bank_reference": "FT002"}, format="json")
    assert resp.status_code == 400
    assert resp.data["code"] == "amount_discrepancy"
    assert resp.data["expected"] == "10000.00" and resp.data["received"] == "6000.00"
    order.refresh_from_db()
    assert order.status == "pending_payment"


def test_a_duplicate_bank_reference_returns_409(two_bank_transfer_orders, staff_user):
    (o1, _), (o2, _) = two_bank_transfer_orders
    client = APIClient(); client.force_authenticate(staff_user)
    client.post(_url(o1), {"amount_received": "10000.00",
                           "bank_reference": "FT-DUP"}, format="json")
    resp = client.post(_url(o2), {"amount_received": "10000.00",
                                  "bank_reference": "FT-DUP"}, format="json")
    assert resp.status_code == 409
    o2.refresh_from_db()
    assert o2.status == "pending_payment"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest apps/payments/tests/test_admin_confirm_api.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Write the implementation**

Follow the existing staff refund view's permission class and error shape exactly — match it, do not invent a convention.

```python
class ConfirmManualReceiptSerializer(serializers.Serializer):
    amount_received = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    bank_reference = serializers.CharField(max_length=128)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    accept_discrepancy = serializers.BooleanField(required=False, default=False)
    allow_duplicate_reference = serializers.BooleanField(required=False, default=False)


@api_view(["POST"])
@permission_classes([IsAdminUser])
def confirm_manual_receipt_view(request, number):
    """POST /api/v1/admin/orders/{number}/confirm-payment/ — staff confirm a bank transfer
    landed. This is the ONLY way a bank-transfer order can ever be fulfilled."""
    order = get_object_or_404(Order, number=number)
    payment = order.payments.filter(gateway="bank_transfer").order_by("-id").first()
    if payment is None:
        return Response({"detail": "This order has no bank transfer payment to confirm."},
                        status=400)

    serializer = ConfirmManualReceiptSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        confirm_manual_receipt(payment, staff_user=request.user, **serializer.validated_data)
    except AmountDiscrepancy as exc:
        # Not a system error — a decision the human must make. Return the numbers so the
        # UI can offer "accept and fulfil" rather than just failing.
        return Response(
            {"detail": str(exc), "code": "amount_discrepancy",
             "expected": str(exc.expected), "received": str(exc.received)},
            status=400,
        )
    except DuplicateBankReference as exc:
        return Response({"detail": str(exc), "code": "duplicate_bank_reference"}, status=409)
    except ValueError as exc:
        return Response({"detail": str(exc), "code": "invalid_confirmation"}, status=400)

    order.refresh_from_db()
    return Response({"status": order.status, "review_reason": order.review_reason})
```

Wire the route in `backend/apps/payments/admin_urls.py`, matching the existing refund route's pattern:

```python
    path("orders/<str:number>/confirm-payment/", confirm_manual_receipt_view,
         name="admin-confirm-manual-receipt"),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest apps/payments/tests/test_admin_confirm_api.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/payments/views.py backend/apps/payments/admin_urls.py backend/apps/payments/tests/test_admin_confirm_api.py
git commit -m "feat(payments): admin confirm-receipt endpoint for bank transfers"
```

---

### Task 9: The customer's verify endpoint must not try to verify a manual gateway

`PaymentStatusView` (`views.py:29`) is `POST /api/v1/payments/{reference}/verify/`, looked up by `gateway_reference` — which for bank_transfer is the **order number** (`_initiate_payment` sets `payment.gateway_reference = init.reference`, and `BankTransferGateway.initiate` returns `order.number`). It returns `{"order_number", "order_status", "payment_status"}`. **Return exactly those keys** — the storefront must not get a different shape from the same URL depending on gateway.

Today `confirm_payment` → `verify()` → `ManualVerificationOnly`, which *is* a `GatewayError`, so line 43 already catches it and the endpoint answers. This task makes the intent explicit and saves a pointless raise; it is a clarity fix, not a bug fix. Keep the `except GatewayError` as belt-and-braces.

**Files:**
- Modify: `backend/apps/payments/views.py`
- Test: `backend/apps/payments/tests/test_customer_check_payment.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/payments/tests/test_customer_check_payment.py
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_verify_on_a_bank_transfer_reports_status_without_asking_a_gateway(
    bank_transfer_order, customer_user, monkeypatch
):
    order, payment = bank_transfer_order
    called = []
    monkeypatch.setattr(
        "apps.payments.gateways.bank_transfer.BankTransferGateway.verify",
        lambda self, p: called.append(1),
    )
    client = APIClient(); client.force_authenticate(customer_user)
    resp = client.post(f"/api/v1/payments/{payment.gateway_reference}/verify/")
    assert resp.status_code == 200
    assert not called                       # there is nothing to ask
    # Same contract as every other gateway — the shape must not depend on payment method.
    assert set(resp.data) == {"order_number", "order_status", "payment_status"}
    assert resp.data["order_status"] == "pending_payment"
```

> **Implementer note:** `customer_user` must own the order (`order__user=request.user` scoping). Read `views.py:29-55` and mirror its exact response construction rather than rebuilding the dict.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest apps/payments/tests/test_customer_check_payment.py -v`
Expected: FAIL — `verify()` was called.

- [ ] **Step 3: Write minimal implementation**

In `PaymentStatusView.post`, before the `try:` at line 41:

```python
        # A manual gateway has no machine to ask — skip straight to reporting state.
        # Branching on `confirmation` rather than relying on ManualVerificationOnly being
        # caught below makes the intent explicit; the except stays as belt-and-braces.
        if get_gateway(payment.gateway).confirmation != "manual":
            try:
                confirm_payment(payment)
            except GatewayError:
                logger.warning("Return-verify for %s could not reach gateway", reference)
```

(Restructure the existing `try` into this branch; leave everything from `payment.refresh_from_db()` onward untouched so the response shape is literally the same code.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest apps/payments/tests/test_customer_check_payment.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/payments/views.py backend/apps/payments/tests/test_customer_check_payment.py
git commit -m "fix(payments): verify endpoint skips the gateway for manual payments"
```

---

### Task 10: The `order_received` email must carry every per-market field

**This silently disables GB and US.** `apps/notifications/templates/email/order_received.txt` hardcodes:

```
{% if bank_name %}
  Bank:           {{ bank_name }}
  Account name:   {{ account_name }}
  Account number: {{ account_number }}
{% endif %}
```

`enqueue_order_received` spreads `init.data` into the context, so Task 4's `**account.extra` (`sort_code`, `routing_number`, IBAN/SWIFT) **arrives and is silently dropped**. A UK domestic transfer cannot be made without a sort code, and this email is the customer's only durable copy. The email must also state the **24h deadline** — nothing anywhere tells the customer their reservation expires, which is the single fact most likely to make them transfer today rather than Saturday.

**Files:**
- Modify: `backend/apps/notifications/templates/email/order_received.txt`, `.../order_received.html`, `backend/apps/orders/emails.py`, `backend/apps/payments/gateways/bank_transfer.py`
- Test: `backend/apps/orders/tests/test_order_received_email.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/orders/tests/test_order_received_email.py
import pytest
from django.core import mail

pytestmark = pytest.mark.django_db


def test_a_uk_customer_gets_their_sort_code(gb_bank_transfer_checkout):
    # Without it a UK domestic transfer is impossible and the order dies at the 24h TTL.
    order = gb_bank_transfer_checkout(extra={"sort_code": "04-00-04"})
    body = mail.outbox[0].body
    assert "04-00-04" in body
    assert "Sort code" in body


def test_a_us_customer_gets_their_routing_number(gb_bank_transfer_checkout):
    order = gb_bank_transfer_checkout(country="US", extra={"routing_number": "021000021"})
    assert "021000021" in mail.outbox[0].body


def test_the_email_states_the_payment_deadline(gb_bank_transfer_checkout):
    gb_bank_transfer_checkout(extra={"sort_code": "04-00-04"})
    body = mail.outbox[0].body
    assert "24 hours" in body


def test_internal_fields_are_not_shown_to_the_customer(gb_bank_transfer_checkout):
    # init.data carries amount/currency/reference/instructions alongside the account
    # fields; the details block must render account details, not our plumbing.
    body = mail.outbox[0].body
    gb_bank_transfer_checkout(extra={"sort_code": "04-00-04"})
    assert "instructions" not in mail.outbox[0].body.lower().split("how to pay")[-1][:200]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest apps/orders/tests/test_order_received_email.py -v`
Expected: FAIL — the sort code is absent from the body.

- [ ] **Step 3: Pass the account details as one structured dict**

Spreading `init.data` into the flat template context is what made the extra fields unrenderable. Give the template one ordered dict to iterate.

In `BankTransferGateway.initiate`, add a display-ready block alongside the flat keys (keep the flat ones — the checkout API response and `Payment.raw_response` consumers rely on them):

```python
                # Ordered, display-ready, per-market. The email iterates this rather than
                # naming fields, so a market that needs a sort code or SWIFT gets it
                # without a template change. Labels are what the customer reads.
                "bank_details": {
                    "Bank": account.bank_name,
                    "Account name": account.account_name,
                    "Account number": account.account_number,
                    **{k.replace("_", " ").capitalize(): v for k, v in account.extra.items()},
                },
```

In `order_received.txt`, replace the hardcoded block:

```
HOW TO PAY
{% if bank_details %}{% for label, value in bank_details.items %}
  {{ label }}: {{ value }}
{% endfor %}{% endif %}
  Amount:         {{ grand_total }}
  Reference:      {{ number }}

IMPORTANT: please use {{ number }} as the transfer reference. Without it we may not
be able to match your payment to this order.

Please transfer within 24 hours — we're holding your items until then.
```

Mirror the same change in `order_received.html` (keep its existing table/markup idiom; **the base template's charset declaration is load-bearing — a missing one renders every ₦ as "â‚¦"**).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest apps/orders/tests/test_order_received_email.py -v`
Expected: 4 passed

- [ ] **Step 5: Render both templates and READ them**

Plan-10 shipped two bugs a green suite missed and only reading the rendered output caught. Render the NG, GB and US variants; confirm the ₦/£/$ symbol, that every account field a customer needs is present and labelled, and that the 24h deadline reads clearly.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/notifications/templates/email/order_received.* backend/apps/payments/gateways/bank_transfer.py backend/apps/orders/tests/test_order_received_email.py
git commit -m "fix(orders): order_received carries every per-market bank field + the deadline"
```

---

### Task 11: Expired-manual-order email

A customer who wired money 25 hours ago must not learn their order died from silence.

**The sweep has no poison isolation despite its docstring.** Calling `get_gateway()` in the loop raises `UnknownGateway` for a legacy gateway code (879 migrated NG orders are inbound in Plan-21/23) — that order never expires, the exception kills the task run, and **every due order behind it starves, every 5 minutes, forever**. Derive a code set once and wrap each iteration.

**Files:**
- Modify: `backend/apps/checkout/tasks.py`, `backend/apps/orders/tasks.py`
- Create: `backend/apps/notifications/templates/email/order_expired_manual.{txt,html,subject.txt}`
- Test: `backend/apps/checkout/tests/test_expiry_email.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/apps/checkout/tests/test_expiry_email.py
import pytest
from django.core import mail
from django.utils import timezone

from apps.checkout.tasks import expire_pending_orders

pytestmark = pytest.mark.django_db


def _make_due(order):
    order.reservation_expires_at = timezone.now() - timezone.timedelta(seconds=1)
    order.save(update_fields=["reservation_expires_at"])


def test_expiring_a_bank_transfer_order_emails_the_customer(bank_transfer_order):
    order, _ = bank_transfer_order
    _make_due(order)
    expire_pending_orders()
    order.refresh_from_db()
    assert order.status == "expired"
    assert len(mail.outbox) == 1
    assert order.number in mail.outbox[0].body


def test_expiring_a_card_order_sends_no_such_email(paystack_order):
    # A card that never completed means the customer never sent money — nothing to explain.
    order, _ = paystack_order
    _make_due(order)
    expire_pending_orders()
    assert len(mail.outbox) == 0


def test_an_unknown_legacy_gateway_does_not_starve_every_other_order(
    bank_transfer_order, legacy_gateway_order
):
    # 879 migrated NG orders are inbound; one unknown gateway code must not kill the sweep
    # and starve every order behind it every 5 minutes forever.
    good, _ = bank_transfer_order
    legacy, _ = legacy_gateway_order      # Payment(gateway="woocommerce_legacy")
    _make_due(good); _make_due(legacy)
    expire_pending_orders()               # must not raise
    good.refresh_from_db()
    assert good.status == "expired"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest apps/checkout/tests/test_expiry_email.py -v`
Expected: FAIL — no email sent.

- [ ] **Step 3: Write the implementation**

In `backend/apps/checkout/tasks.py`:

```python
def _manual_gateway_codes() -> frozenset[str]:
    """Codes confirmed by a human. Derived once from the registry — NOT get_gateway() per
    order: a migrated order carrying a gateway code the registry never heard of would
    raise UnknownGateway inside the loop, roll back that order, kill the task run, and
    starve every due order behind it on every subsequent beat."""
    from apps.payments.gateways.registry import _REGISTRY

    return frozenset(c for c, g in _REGISTRY.items() if g.confirmation == "manual")


@shared_task
def expire_pending_orders() -> int:
    from apps.orders.models import Order

    manual = _manual_gateway_codes()
    now = timezone.now()
    due_ids = list(
        Order.objects.filter(status="pending_payment", reservation_expires_at__lt=now)
        .values_list("pk", flat=True)
    )
    expired = 0
    for pk in due_ids:
        # Per-order try/except so one poison order cannot starve its siblings — the
        # docstring has always promised this; until now nothing in the loop could raise.
        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=pk)
                if order.status != "pending_payment" or order.reservation_expires_at >= now:
                    continue
                release(reference=order.reservation_reference)
                transition(order, "expired", message="reservation TTL elapsed — stock released")
                if any(p.gateway in manual for p in order.payments.all()):
                    # Their money may already be in our account — silence is the worst
                    # possible answer. on_commit like every other order email.
                    transaction.on_commit(
                        lambda pk=order.pk: send_order_expired_manual_email.delay(pk)
                    )
                expired += 1
        except Exception:
            logger.exception("expire_pending_orders: order %s failed to expire", pk)
    return expired
```

Add `send_order_expired_manual_email` to `backend/apps/orders/tasks.py` following the existing transactional-email task pattern exactly (shared_task taking an order pk, rendering, sending via the standard wrapper).

The template must say: the reservation lapsed and the items were released; **if they have already sent the money, contact support with the order number and it will be honoured**; nothing was charged automatically.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest apps/checkout/tests/test_expiry_email.py -v`
Expected: 3 passed

- [ ] **Step 5: Render the email and READ it**

Confirm the currency symbol, the order number, and that the "if you already sent the money" instruction is unmissable — that customer is the one whose money we may be holding.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/checkout/tasks.py backend/apps/orders/tasks.py backend/apps/notifications/templates/email/order_expired_manual.* backend/apps/checkout/tests/test_expiry_email.py
git commit -m "feat(orders): tell the customer when a bank-transfer order expires"
```

---

### Task 12: Manual refunds — the second dead end

`BankTransferGateway` never implements `refund()`, so it inherits `base.py:113`'s bare `raise NotImplementedError`. `create_refund` (refunds.py:94) catches only `GatewayError` — and `NotImplementedError` is a `RuntimeError`, so it **escapes**, the staff request 500s, **and the `pending` Refund row from phase 1 is never resolved**. `refundable_amount` counts pending rows, so that amount is reserved forever and every later refund on that payment fails `amount_exceeds_remaining`. One 500 poisons the payment permanently.

This is a launch blocker of the same class as the confirm gap: with transfers the only method, **every refund in every market takes this path** — and Plan-09b's own ladder and overpayment flags all say "refund it".

**Files:**
- Modify: `backend/apps/payments/gateways/base.py`, `.../bank_transfer.py`, `backend/apps/payments/refunds.py`, `backend/apps/payments/views.py`, `backend/apps/payments/admin_urls.py`
- Test: `backend/apps/payments/tests/test_manual_refund.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/apps/payments/tests/test_manual_refund.py
from decimal import Decimal

import pytest

from apps.payments.gateways.base import GatewayError
from apps.payments.refunds import create_refund, record_manual_refund, refundable_amount

pytestmark = pytest.mark.django_db


def test_recording_a_manual_refund_updates_the_ledger_and_lifecycle(fulfilled_bt_order, staff_user):
    order, payment = fulfilled_bt_order        # succeeded, 10000 NGN
    refund = record_manual_refund(
        payment=payment, amount=Decimal("10000.00"), staff_user=staff_user,
        bank_reference="RF001", note="returned item",
    )
    order.refresh_from_db(); payment.refresh_from_db()
    assert refund.status == "succeeded"
    assert refund.gateway_reference == "RF001"
    assert payment.status == "refunded"
    assert order.status == "refunded"


def test_a_manual_refund_is_audited_with_its_actor(fulfilled_bt_order, staff_user):
    order, payment = fulfilled_bt_order
    record_manual_refund(payment=payment, amount=Decimal("2000.00"), staff_user=staff_user,
                         bank_reference="RF002", note="overpayment surplus")
    event = order.events.get(type="refund_recorded_manually")
    assert event.actor == staff_user
    assert "RF002" in event.message


def test_a_partial_manual_refund_leaves_the_lifecycle_alone(shipped_bt_order, staff_user):
    # Plan-09's rule: a partial refund is a ledger fact, not a lifecycle move. Stomping a
    # shipped order drops it out of the packing pipeline while goods are still owed.
    order, payment = shipped_bt_order
    record_manual_refund(payment=payment, amount=Decimal("2000.00"), staff_user=staff_user,
                         bank_reference="RF003", note="partial")
    order.refresh_from_db(); payment.refresh_from_db()
    assert order.status == "shipped"
    assert payment.status == "partially_refunded"


def test_create_refund_on_a_manual_gateway_fails_clean_without_wedging_a_pending_row(
    fulfilled_bt_order, staff_user
):
    # The old NotImplementedError escaped `except GatewayError`, 500'd, and left a pending
    # row that reserved the amount forever — every later refund then hit
    # amount_exceeds_remaining.
    order, payment = fulfilled_bt_order
    before = refundable_amount(payment)
    with pytest.raises(GatewayError, match="manually"):
        create_refund(payment=payment, amount=Decimal("5000.00"), user=staff_user)
    payment.refresh_from_db()
    assert refundable_amount(payment) == before      # nothing reserved
    assert not payment.refunds.filter(status="pending").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest apps/payments/tests/test_manual_refund.py -v`
Expected: FAIL — `ImportError: cannot import name 'record_manual_refund'`

- [ ] **Step 3: Add the exception and the gateway override**

In `backend/apps/payments/gateways/base.py`, beside `ManualVerificationOnly`:

```python
class ManualRefundOnly(GatewayError):
    """This gateway cannot push money back — a human sends the transfer and records it.

    A GatewayError (unlike the base refund()'s NotImplementedError) so create_refund's
    existing handler catches it, marks the reserved Refund row failed, and frees the
    amount instead of 500ing and wedging that payment's refundable balance forever.
    """
```

In `BankTransferGateway`:

```python
    def refund(self, payment, amount, reason: str = ""):
        """No API to push money back — staff wire it from the bank and record it via
        payments.refunds.record_manual_refund. Reaching here means a caller routed a manual
        payment through the gateway refund path; fail in the gateway vocabulary so the
        reserved Refund row is released rather than stranded."""
        raise ManualRefundOnly(
            "bank_transfer refunds are sent by a human — use record_manual_refund()"
        )
```

- [ ] **Step 4: Add `record_manual_refund`**

In `backend/apps/payments/refunds.py` — reuse `apply_succeeded_refund`, which already does the ledger roll-up, lifecycle, restock and email, and whose docstring already names itself the entry point for advancing a refund that completed out of band:

```python
def record_manual_refund(*, payment, amount: Decimal, staff_user, bank_reference: str,
                         note: str = "", restock: bool = False):
    """Record a refund a human already sent from the bank. The mirror of
    confirm_manual_receipt: the money moved outside the system, and this makes it visible.

    Unlike create_refund there is no pending phase — the transfer has ALREADY been sent by
    the time staff record it, so the row is born `succeeded`. Writing it as pending first
    would reserve the amount against a gateway call that is never coming.
    """
    from apps.orders.state import record_event

    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        if locked.status not in _REFUNDABLE_PAYMENT_STATES:
            raise RefundError(
                "payment_not_refundable",
                f"Payment is {locked.status}; only a collected payment can be refunded.",
            )
        remaining = refundable_amount(locked)
        if amount > remaining:
            raise RefundError(
                "amount_exceeds_remaining",
                f"Only {remaining} remains refundable on this payment.",
            )
        if restock and amount != locked.amount:
            raise RefundError(
                "restock_requires_full_refund",
                "Restock is only supported on a full refund; refund without restock and "
                "adjust stock manually.",
            )
        refund = Refund.objects.create(
            payment=locked, amount=amount, reason=note, status="succeeded",
            gateway_reference=bank_reference, created_by=staff_user,
            raw_response={"manual": True, "bank_reference": bank_reference,
                          "recorded_by": staff_user.get_username()},
        )

    record_event(
        payment.order, "refund_recorded_manually", actor=staff_user,
        message=f"{amount} {payment.currency_id} refunded via bank reference {bank_reference}"
                + (f" — {note}" if note else ""),
    )
    apply_succeeded_refund(refund, restock=restock, user=staff_user)
    return refund
```

> Match `RefundError`'s real constructor and `_REFUNDABLE_PAYMENT_STATES` as they exist in the file. The validation above intentionally mirrors `create_refund`'s — if that duplication bothers you, extract a shared `_validate_refundable(locked, amount, restock)` and call it from both. Do not skip the validation.

- [ ] **Step 5: Add the admin endpoint**

`POST /api/v1/admin/orders/{number}/manual-refund/`, staff-only, body `{amount, bank_reference, note, restock}`, mirroring Task 8's view and the existing refund view's error shape. Map `RefundError` to 400 with its code.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest apps/payments/tests/test_manual_refund.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add backend/apps/payments/ 
git commit -m "feat(payments): manual refunds for bank transfer; stop wedging pending rows"
```

---

### Task 13: Deactivate the four networked gateways; open bank transfer everywhere

**`is_active` gates the checkout menu and `initiate()` — never `confirm_payment()`.** Deactivation must not strand a customer who genuinely paid a gateway minutes before the deploy.

**The reverse must be a no-op.** The guide's rule is "no gateway is reactivated until its test-mode payment is driven end-to-end and shown to Hammed". A `migrate payments 0006` run for any unrelated reason (bisecting a bad 0008, a rollback during an incident) would otherwise silently flip four uncertified gateways live in production. Reactivation is a human checkpoint procedure, not schema symmetry.

**Files:**
- Create: `backend/apps/payments/migrations/0007_launch_bank_transfer_only.py`
- Test: `backend/apps/payments/tests/test_launch_gateway_state.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/payments/tests/test_launch_gateway_state.py
import pytest

from apps.core.models import Country
from apps.payments.gateways.registry import active_gateways_for

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("code", ["NG", "GB", "US", "CA", "ZZ"])
def test_bank_transfer_is_the_only_active_method_in_every_market(code):
    active = {g["gateway"] for g in active_gateways_for(Country.objects.get(code=code))}
    assert active == {"bank_transfer"}


def test_a_deactivated_gateway_can_still_confirm_money_already_taken(paystack_order, monkeypatch):
    # A customer who genuinely paid minutes before the deploy must still be fulfillable.
    # is_active gates the MENU, never the money.
    from apps.payments.gateways.base import VerifyResult
    from apps.payments.services import confirm_payment

    order, payment = paystack_order
    monkeypatch.setattr(
        "apps.payments.gateways.paystack.PaystackGateway.verify",
        lambda self, p: VerifyResult(status="succeeded", amount=p.amount,
                                     currency=p.currency_id, raw={}),
    )
    confirm_payment(payment)
    order.refresh_from_db()
    assert order.status == "processing"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest apps/payments/tests/test_launch_gateway_state.py -v`
Expected: FAIL — NG has paystack/flutterwave active; GB/US/CA/ZZ have stripe/paypal and no bank_transfer row.

- [ ] **Step 3: Write the data migration**

```python
# backend/apps/payments/migrations/0007_launch_bank_transfer_only.py
"""Launch on bank transfer only (guide decision #3, 2026-07-16).

The four networked gateways are code-complete but their sandbox checkpoint was never done
— test-mode keys never arrived. Deactivating them is what makes deferring that checkpoint
safe: uncertified code that cannot be reached takes no money.

is_active gates the checkout menu and initiate(), NOT confirm_payment — money already taken
must always remain confirmable.
"""
from django.db import migrations

NETWORKED = ["paystack", "flutterwave", "stripe", "paypal"]
MARKETS = ["NG", "GB", "US", "CA", "ZZ"]


def bank_transfer_only(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    CPG = apps.get_model("payments", "CountryPaymentGateway")

    CPG.objects.filter(gateway__in=NETWORKED).update(is_active=False)

    for code in MARKETS:
        country = Country.objects.filter(code=code).first()
        if not country:
            continue
        CPG.objects.update_or_create(
            country=country, gateway="bank_transfer",
            defaults={"is_active": True, "sort_order": 1},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0006_bankaccount"),
        # Without this, a fresh DB may run us before Country rows exist: every
        # `if not country: continue` fires, bank transfer activates in ZERO markets, and
        # the site silently takes no money anywhere.
        ("core", "0003_seed_countries_currencies"),
    ]
    operations = [
        # Reverse is a deliberate no-op: reactivating a gateway is a human checkpoint
        # (drive its test-mode payment e2e first), never a side effect of a rollback.
        migrations.RunPython(bank_transfer_only, migrations.RunPython.noop),
    ]
```

- [ ] **Step 4: Apply and run the tests**

Run: `cd backend && uv run python manage.py migrate && uv run pytest apps/payments/tests/test_launch_gateway_state.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/payments/migrations/0007_launch_bank_transfer_only.py backend/apps/payments/tests/test_launch_gateway_state.py
git commit -m "feat(payments): launch on bank transfer only; deactivate networked gateways"
```

---

### Task 14: `payments.W002` — a market with bank transfer live but no account

**Files:**
- Modify: `backend/apps/payments/checks.py`
- Test: `backend/apps/payments/tests/test_checks.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/apps/payments/tests/test_checks.py  (add to the existing file)
def test_warns_when_a_country_has_bank_transfer_live_but_no_account(db):
    # Migration 0007 activates bank_transfer in all 5 markets; a fresh DB has no
    # BankAccount rows, so every market is stranded.
    from apps.payments.checks import gateway_configuration_check

    assert "payments.W002" in [w.id for w in gateway_configuration_check(None)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest apps/payments/tests/test_checks.py -v`
Expected: FAIL — only `payments.W001` is emitted.

- [ ] **Step 3: Write minimal implementation**

Append inside `gateway_configuration_check` (add `from django.db.utils import OperationalError, ProgrammingError`):

```python
    # Bank transfer needs no API keys — it needs an ACCOUNT. Same failure shape as a
    # missing secret: live for a country, unusable in practice. Checkout now refuses such
    # an order outright (rather than reserving stock and 503ing), so a stranded market
    # simply cannot sell — worth knowing at deploy, not from a customer.
    try:
        from apps.payments.models import BankAccount, CountryPaymentGateway

        live = CountryPaymentGateway.objects.filter(gateway="bank_transfer", is_active=True)
        funded = set(
            BankAccount.objects.filter(is_active=True).values_list("country_id", flat=True)
        )
        stranded = sorted(str(r.country_id) for r in live if r.country_id not in funded)
        if stranded:
            issues.append(
                Warning(
                    "bank_transfer is active but has no BankAccount for: " + ", ".join(stranded),
                    hint=(
                        "Customers in those countries cannot check out at all. Add a "
                        "BankAccount in Django admin, or deactivate bank_transfer there. "
                        "Bank transfer is the only live method at launch."
                    ),
                    id="payments.W002",
                )
            )
    except (OperationalError, ProgrammingError):
        pass  # DB not migrated yet (fresh checkout / first migrate) — nothing to say
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest apps/payments/tests/test_checks.py -v`
Expected: passed

- [ ] **Step 5: Commit**

```bash
git add backend/apps/payments/checks.py backend/apps/payments/tests/test_checks.py
git commit -m "feat(payments): warn when a market has bank transfer live but no account"
```

---

### Task 15: Documentation, storefront gaps, and full verification

**Files:**
- Modify: `backend/docs/architecture.md`, `backend/.env.example`, `master-tokerebuild.md`

- [ ] **Step 1: Document the design**

Add architecture.md § "Manual payments (Plan-09b)" covering:
- Why `bank_transfer` was a dead end twice (confirm and refund) and what closed each.
- **`confirmation` vs `InitiateResult.action`** — two adjacent concepts answering different questions (`action == "bank_details"` = "did the customer leave holding instructions", which is why the `order_received` email keys off it; `confirmation` = "can this be verify()'d / which TTL"). State this explicitly or the next reader will "unify" them wrongly.
- Why any nonzero delta requires an explicit accept + reason, and why overpayment fulfils.
- Why `_flag_review` appends, and that `resolve_review` is still the single clearing act.
- **Accounting caveat:** on an accepted discrepancy, `payment.amount` stays the order total while the real cash received lives in `raw_response.manual_receipt`. Refunding a surplus through the ledger therefore reads as a *partial refund of the order price*. Acceptable at launch — **but do not trust `payment.amount` as cash-in for reporting** (Plan-20/28).
- That `is_active` gates the menu and never `confirm_payment`, plus the gateway reactivation procedure: drive the deferred Plan-09 sandbox checkpoint first, then flip `is_active`.

- [ ] **Step 2: Note the TTL change in `.env.example`**

`RESERVATION_TTL_MINUTES` now tunes **card** gateways only; bank transfer is fixed at 24h on the gateway class.

- [ ] **Step 3: Record two follow-ups in the guide (do NOT build them here)**

24h TTL × only-method means **every "place order" click holds stock for a day**, including customers who only wanted to see the account number and walked. With thin NG stock, three abandoned checkouts can sell out a variant for 24h against real buyers. Add to the guide:
- **Plan-14 (storefront checkout):** expose customer-visible cancel on a pending order — `orders.services.cancel_order` already exists; the storefront must surface it. Also re-surface the bank details on the order page (today they live only in the checkout response and the email).
- **Plan-20 (dashboard/reports):** the low-stock digest counts reserved stock, so staff will chase phantom sell-outs during the 24h window unless it distinguishes reserved from sold.

- [ ] **Step 4: Full suite + lint + checks**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run python manage.py check`
Expected: all pass (baseline 328 + ~40 added here), ruff clean, only the expected `payments.W001`/`W002`.

- [ ] **Step 5: Driven end-to-end verification — do NOT skip**

Tests mock; this stage exists because a green suite already hid two Plan-10 bugs. With a dev server and `BankAccount` rows seeded for NG and GB:

1. Place an order in NG → the **NG** account renders; reservation ~24h out.
2. Place an order in GB → the **GB** account renders (not NG), **including the sort code**.
3. Place an order in CA (no account) → clean 400 at checkout, **no order created, no stock reserved**.
4. Read the GB `order_received` email → sort code present, ₦/£ correct, 24h deadline stated.
5. Confirm the exact amount → `processing`, stock committed, `OrderEvent` shows actor + bank reference.
6. Confirm a different amount → 400 with expected/received; order untouched.
7. Re-confirm with `accept_discrepancy` + reason → `processing` + `review_reason` names the delta.
8. Reuse the same `bank_reference` on a second order → 409.
9. Record a manual refund → payment `refunded`, order `refunded`, event shows the actor.
10. Read the rendered expiry email.

- [ ] **Step 6: Commit and open the checkpoint**

```bash
git add backend/docs/architecture.md backend/.env.example ../master-tokerebuild.md
git commit -m "docs(payments): Plan-09b manual payments design + reactivation procedure"
```

**CHECKPOINT — show Hammed:** a bank-transfer order in each market going placed → bank details → admin confirm → processing, the GB email with its sort code, a manual refund, and the audit trail. Do not merge to main before this.

---

## Self-review notes

- **Spec coverage:** guide §Plan-09b items 1–11 map to Tasks 2–14. Spec item 3's claim that `supported_currencies` gates the payment-methods menu is **false** and must be corrected in the guide during Task 15 — the gating lives in `place_order` (Task 4).
- **Naming consistency:** `confirmation`, `reservation_ttl_minutes`, `confirm_manual_receipt`, `record_manual_refund`, `_react_to_verdict` (returns `bool`), `AmountDiscrepancy`, `DuplicateBankReference`, `ManualRefundOnly`, `accept_discrepancy`, `allow_duplicate_reference`, `payments.W002` are used identically throughout.
- **Deliberately NOT built (YAGNI — the exit is Paystack dedicated accounts, so the manual flow must not grow features that assume it is permanent):** installment/partial-payment ledgers; automated bank-statement reconciliation or CSV import; per-country TTL tuning; a `BankAccount` CRUD screen beyond Django admin; matching transfers to orders by anything but a human reading the reference.
- **Known soft spots:** the fixtures (`bank_transfer_order`, `two_bank_transfer_orders`, `paystack_order`, `fulfilled_bt_order`, `shipped_bt_order`, `expired_order_no_stock`, `cancelled_order_with_payment`, `legacy_gateway_order`, `gb_bank_transfer_checkout`, `place_order_via`, `ca_cart_ctx`) are specified but not written — build them on the existing factories and fix the factories rather than duplicating setup. `from_minor` may not exist in `money.py` (Task 7).
