# Plan-09 Payments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Follow TDD: write the failing test, watch it fail, minimal implementation, watch it pass, commit.

**Goal:** Four payment gateways (Paystack, Flutterwave, Stripe, PayPal) behind one interface, with signature-verified idempotent webhooks, server-side re-verification before fulfilment, and staff refunds.

**Architecture:** All gateways sit behind the existing `PaymentGateway` ABC (proven in Plan-08d by `bank_transfer`). Webhooks are only a *trigger*: the money truth always comes from a server-side `gateway.verify()` call, wrapped by a single `payments.services.confirm_payment()` seam that does the amount+currency equality check and then calls the existing idempotent `mark_paid()`. Webhook delivery is deduplicated by a `WebhookEvent(gateway, event_id)` ledger; processing is offloaded to a Celery task so the endpoint returns 200 fast.

**Tech Stack:** Django 5.2 + DRF, Celery (eager in dev/tests), Postgres (dev via docker-compose on :5433), Redis (:6380), `httpx` for Paystack/Flutterwave/PayPal, `stripe-python` SDK for Stripe, `respx` for mocked-HTTP unit tests.

---

## STATUS (2026-07-16): code-complete, NOT done

All eight tasks below are implemented and green — **249 tests passing** (was 171 at Plan-08),
ruff clean, `manage.py check` clean. The design write-up landed in `docs/architecture.md`
§ "Payments (Plan-09)".

**Plan-09 does NOT get marked done until the PENDING CHECKPOINT at the bottom of this file
passes** — real test-mode e2e per gateway. Blocked on test-mode API keys from Hammed.
Every gateway is "code-complete, unverified against sandbox" until then, because the whole
suite mocks HTTP and therefore encodes our *assumptions* about each API.

Two bugs found and fixed along the way that were NOT in the original plan:
1. Refund-completion webhooks were being routed through `confirm_payment`, which would
   re-verify an already-refunded payment and raise a **bogus double-payment flag**. Fixed
   with `ParsedEvent.kind` classification per adapter.
2. Plan-08's recorded risks #2 and #4 (post-commit initiate failure leaving an empty
   `payment.action`; a failed checkout holding the Idempotency-Key for 5 min) are both
   resolved by the 502 + `idempotency.clear()` + durable-backstop-resume path.

---

## Authoritative design decisions (Fable 5 rulings, 2026-07-15)

These override any conflicting instinct. Rationale is in the commit history / this session.

1. **Build against mocked HTTP + computed signature fixtures.** Ship all of Plan-09 fully unit-tested without the real gateway keys. Real test-mode e2e per gateway is a **PENDING checkpoint** (needs keys from Hammed) — each gateway is "code-complete, unverified against sandbox" until that passes, never "done".
2. **Signature fixtures are computed, never hand-pasted.** Each webhook test computes the signature by running the real algorithm over the exact raw body bytes in test setup. A precomputed hex string next to a JSON body rots the moment the body is re-serialized.
3. **`needs_review` stays a `status` value** for the pre-fulfillment flag cases (amount mismatch, expired-and-couldn't-re-reserve, cancelled-order payment). ADD `Order.review_reason = TextField(blank=True)` as the orthogonal, **single source of truth for "a human must look"**. Write `review_reason` in *every* flag path (including when flipping status to `needs_review`). The genuinely-orthogonal double-payment case leaves `status='processing'` and sets `review_reason` only. Admin "needs attention" filter = `status == 'needs_review' OR review_reason != ''`. (Plan-10's `transition()` clears `review_reason` when resolving.)
4. **Reuse `Currency.decimal_places`** as the minor-unit exponent (NGN=2, zero-decimal=0). Do NOT add a new field. The Stripe zero-decimal test uses a currency row with `decimal_places=0`.
5. **Amount check lives in `confirm_payment()`, not `mark_paid()`.** `mark_paid` returns an enum, never writes `succeeded` except via `_fulfil_locked`. `payment.status='succeeded' ⟺ order fulfilled or explicitly recovered`.
6. **`gateway.verify()` is NEVER called while holding the order lock.** Verify first (network, outside any transaction), then open the transaction.
7. **Gateways read keys lazily** (inside methods / `cached_property`), never at import. Register all unconditionally; `initiate()` raises `GatewayNotConfigured` → API 503 when keys are missing.
8. **`Payment` gets a partial unique constraint** on `(gateway, gateway_reference)` where `gateway_reference != ''`; always look up by `(gateway, gateway_reference)`.
9. **Raw body bytes** are captured before any DRF parsing for every signature check.
10. **Per-gateway conventions** (encode in each adapter with a comment):
    - Amount units: Paystack = kobo (minor), Stripe = minor (zero-decimal aware), **Flutterwave = MAJOR (plain NGN)**, **PayPal = major decimal string** (`"10.99"`).
    - Idempotency on initiate: Stripe = `Idempotency-Key` header; Paystack = the `reference` param itself (pass attempt-suffixed `order.reservation_reference`); Flutterwave/PayPal = tx_ref / order id.
    - Webhook event id: Paystack/Stripe/PayPal have native ids; **Flutterwave has none — derive `sha256(f"{tx_ref}:{event_type}:{status}")`**.
11. **HTTP policy:** 15s timeout, retry ×2 with backoff on `httpx.ConnectError`/`ConnectTimeout` **only** — never on 5xx for money-moving calls (rely on gateway idempotency instead).
12. **PayPal signature** uses the hosted `POST /v1/notifications/verify-webhook-signature` endpoint (no local cert-chain verification). Safe because verify() is the real money gate.
13. **Webhook throttle is generous** (gateways retry non-2xx with backoff); signature is the real auth. Unmatched/unknown events: log, record, **return 200**.
14. **Return/callback endpoint** (`confirm_payment` again) so the customer's post-redirect UX doesn't wait on the webhook. Webhook-vs-return is a benign idempotent race.
15. **Refunds can be async** (Flutterwave/PayPal return "pending"); `Refund.status: pending→succeeded/failed`, advanced by refund-completion webhook events. Concurrent staff double-refund guarded by `select_for_update` on the Payment + DB-aggregate of succeeded+pending refunds under lock.

---

## Existing seams (do not recreate)

- `apps/payments/models.py`: `Payment`, `CountryPaymentGateway`.
- `apps/payments/gateways/base.py`: `PaymentGateway` ABC, `InitiateResult`.
- `apps/payments/gateways/bank_transfer.py`, `registry.py`.
- `apps/payments/services.py`: `mark_paid(payment)` — to be refactored (Task 3).
- `apps/inventory/services.py`: `reserve(variant, qty, country, reference)` (reference-idempotent), `release(reference)`, `commit_sale(reference)`, `adjust(stock_item, new_quantity, reason, note, user)`, `InsufficientStock`.
- `apps/orders/models.py`: `Order` (has `status`, `reservation_reference`, `grand_total`, `currency` FK), `OrderItem` (`fulfillment_warehouses` JSON).
- `apps/core/models.py`: `Currency(code pk, decimal_places)`, `Country`.

## Ordered build (Fable 5 checklist → tasks below)

1. **Task 1 — Foundations:** `money.py`, exception hierarchy, `_http.py`, lazy registry, `Payment` partial-unique migration.
2. **Task 2 — Core refactor:** `Order.review_reason`, `_fulfil_locked`, `mark_paid` enum, `confirm_payment()`.
3. **Task 3 — Models + webhook infra:** `Refund`, `WebhookEvent`, gateway-agnostic webhook view + Celery task.
4. **Task 4 — Paystack (the milestone):** full adapter + the entire edge-case battery + client-return endpoint.
5. **Task 5 — Stripe:** SDK, `client_secret` action, zero-decimal path.
6. **Task 6 — Refund API:** partial-refund math, concurrent double-refund guard, optional restock.
7. **Task 7 — Flutterwave + PayPal:** the two remaining adapters (transcription work once the seams are proven).
8. **Task 8 — System checks, docs, env, verification.**

Edge-case battery (Task 4, each a test): duplicate webhook (unique-constraint path), payment succeeds AFTER reservation expired (re-reserve via bumped attempt suffix, else `needs_review`+alert), payment for cancelled order (auto-refund flag + alert), partial refund math, gateway 5xx on initiate (502, order stays pending, retry with same key), double-payment (second verified payment on an already-`processing` order → `review_reason` only).

## Re-reserve-after-expiry (Fable 5 traps — Task 4)

Inside `confirm_payment` when `mark_paid` returns `NOOP_EXPIRED`, all under the order lock:
1. Verify FIRST (outside txn). Then `transaction.atomic()`, `select_for_update` the order, re-check `status=='expired'`.
2. Bump attempt suffix → `new_ref`. `reserve()` each item under `new_ref`.
3. **Partial-reservation leak:** if item N raises `InsufficientStock`, `release(new_ref)` the partial set, set `status='needs_review'` + `review_reason`, alert. (test this exact case.)
4. Write `order.reservation_reference = new_ref` BEFORE `_fulfil_locked` (it reads the reference for `commit_sale` + fulfillment map).
5. Order lock first, always (matches `expire_pending_orders`). Do NOT re-validate the coupon.

## PENDING CHECKPOINT (blocked on keys from Hammed)

Real test-mode e2e per gateway — Paystack test card, Flutterwave test card, Stripe `4242…`, PayPal sandbox — from checkout through webhook (tunnel / `stripe listen`) to order `processing` + stock committed. Show Hammed one full test-mode payment per gateway. **This is the riskiest stage — do not mark Plan-09 "done" until this passes.**

---

## Task detail

Task-by-task steps live in the executing agent's TodoWrite (mirrored from the task list). Each gateway adapter is TDD'd with `respx` (or the Stripe SDK's test helpers) mocking the HTTP layer; signatures are computed in-test per ruling #2. Commits are conventional (`feat(payments): …`), one per green step-group.
