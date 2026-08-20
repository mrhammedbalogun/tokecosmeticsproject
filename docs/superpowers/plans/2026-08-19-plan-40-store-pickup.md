# Plan 40 — Customer pickup at Toke stores (state-matched, ₦0)

**Date:** 2026-08-19 · **Status:** built + verified locally (new backend tests green,
full backend suite green, both frontends typecheck/test/lint green).

## What

The admin "Pickup locations" rows (`SenderLocation`, until now GIG collection origins
only) can be offered to customers as pickup stores. Checkout shows one card —
**"Pickup at Toke Cosmetics Store" · ₦0.00 · "Ready within 24 hours" · "Select to see
nearby store address →"** — mirroring the GIG-centre card. The customer picks a store
(full address + counter phone shown), pays nothing for delivery, and staff later press
**Ready for pickup** on the order, which emails the customer the store's address and
phone.

## Rulings (Hammed, 2026-08-19)

1. **Per-location toggle** (`customer_pickup`) — a GIG-only origin or warehouse never
   shows to customers.
2. **Matched BY STATE, never by LGA** — every opted-in Lagos store shows to every Lagos
   customer. The free-text `state` label was the blocker, so matching runs on a new
   `state_region` FK to the canonical `core.Region` state, picked from a dropdown in
   the admin form (the free-text field survives as a display label the dropdown keeps
   in sync).
3. **Ready-for-pickup email** — a new branded `order_ready_for_pickup` template.
4. **Timing line:** "Ready within 24 hours".
5. **Eligibility:** NG address + NGN order, same gate as partner zones; the card is
   hidden entirely when no store serves the address state.

## How it hangs together

- **Option:** synthesised in `delivery/services.py` (`_store_pickup_option`) and
  appended after partner rows — id `"store_pickup"`, `kind="store"`, price a REAL
  `"0.00"`. The serving stores ride *inside* the option (`stores: [{id, name, address,
  phone, distance_km?}]`, nearest-first when the address has a pin), so the storefront
  picker needs no second endpoint and can never show a store the option would refuse.
- **Placement:** `place_order` takes `pickup_store_id`, re-validates it server-side
  (active + opted-in + same state as the ADDRESS → else `store_invalid`; missing →
  `store_required`, both mirroring the centre rules) and snapshots it onto a new
  `Order.pickup_store` JSONField — the pickup analogue of `GigShipment.centre`, on the
  Order because no courier row exists. `kind="store"` trips neither the GigShipment
  nor the ShippingQuote hook.
- **No new order status.** `Order.status`'s docstring calls a new status the largest
  blast radius in the design, so store pickup reuses `shipped`/`delivered` and changes
  only the words: `enqueue_shipped` branches on `pickup_store` to send
  `order_ready_for_pickup` instead of `order_shipped`; the admin ops panel relabels the
  buttons ("Ready for pickup" / "Picked up"); the storefront StatusChip does the same.
- **Emails:** customer context gains `pickup_store`; `order_confirmation` prints
  "Collect from" + store phone for store-pickup orders; staff alerts' destination line
  reads "{store} (store pickup) — {address}" and `is_pickup` covers both flavours.
- **Admin form:** State is now a dropdown of the 37 canonical NG states
  (`/admin/regions/`), writing `state_region` + syncing the `state` label; saving an
  opted-in store without a state is refused in both the action pre-check and the
  serializer (`validate`) — a store with no state matches nobody and that must never
  be silent.

## Traps for later

- `SenderLocation.state`/`lga` are STILL display-only for GIG — nothing in origin
  selection changed; `state_region` routes customer pickup only.
- The `stores` array (address + phone) is served to anyone with a cart via the
  delivery-options endpoints — deliberate; a pickup store's address and counter phone
  are public business facts.
- Existing rows deploy with `customer_pickup=False`, so the feature ships DARK until
  a store is opted in on /deliveries/pickup-locations (needs its state picked first).
- The order timeline still records the raw `status:shipped` event for pickup orders —
  only labels changed, the machine did not.
