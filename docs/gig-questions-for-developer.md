# Questions for the GIG developer

**From:** Toke Cosmetics (tokecosmetics.com) · 2026-07-30
**Docs reviewed:** <https://gig-logistics.readme.io>
While

---

## What we're building

We're adding GIG as a delivery option for every customer shipping to a Nigerian address.

1. Customer enters a Nigerian address — we capture **state, LGA and street address**, but
   **not GPS coordinates**.
2. At checkout we call `POST /dropOff/price` and show them a live delivery price.
3. Customer pays for the goods and the delivery together, upfront. **No cash on delivery.**
4. We call `POST /create/dropOff` to create the shipment.
5. Our team gets the day's parcels to you — either we drop them at a nearby centre or you
   collect from our office, whichever we agree.
6. You deliver to the customer, and we show them tracking on our site.

We picked the **DropOff** flow because `/dropOff/price` and `/create/dropOff` don't ask for
latitude and longitude, while `/price`, `/price/v3` and `/capture/preshipment` all do. We
don't collect coordinates. Please tell us if that's the wrong call.

---

## The four that are blocking us

**1. `/create/dropOff` gives us a `TempCode`, not a waybill.** It returns something like
`PRE000568-APH`, but `/track/mobileShipment` and `/invoice/generate` both need a `Waybill`.
How do we get the waybill for a drop-off shipment? Is it issued when we hand the parcel
over, or can we look it up by `TempCode`? Right now we can't track or print labels.

**2. Can you send us real sample responses for `GET /lga/active` and
`GET /homedelivery/active`?** Both show an empty `"data": {}` in the docs, so we can't see
the fields. These are the two endpoints that tell us where you deliver.

**3. How do we map a customer's state + LGA to `ReceiverStationId` and
`DestinationServiceCenterId`?** We hold all 37 states and 774 LGAs. Is there an endpoint
that resolves an LGA to the right station and centre, or do we build that table ourselves
and maintain it?

**4. Before we quote, how do we know you actually deliver to an address?** We'd rather hide
the GIG option than show a price and fail after the customer has paid.

---

## Access

5. We've been given an email and password — please confirm they're for the **development**
   environment (`dev-thirdpartynode.theagilitysystems.com`), and tell us what's needed to
   get **production** access.

6. How long is the `access-token` from `/login` valid? There's no refresh endpoint, so
   should we re-login on a schedule or only after a `401`?

7. Any rate limit on `/dropOff/price`? We'd be calling it live during checkout.

## Flow

8. Does the API flow change depending on whether we drop parcels at a centre or you collect
   from our office? Or is `/create/dropOff` correct either way?

9. Confirming our reading of **`PickUpOptions`**: `0` = you deliver to the customer's
   address, `1` = the customer collects from a GIG centre. Right?

10. What does **`DeliveryType`** (`0` or `1`) mean? It's required on the drop-off endpoints
    but isn't explained anywhere in the docs.

11. **`ShipmentType`** is `0|1` on `/dropOff/price` but `/price/v3` lists
    `2 = Ecommerce`. Which value should we be sending as an online store?

## Pricing

12. In the `/dropOff/price` response — `MainCharge`, `DeliverPrice`, `PickupCharge`,
    `InsuranceValue`, `GrandTotal`, `DeclaredValue`, `Discount` — **which single number do
    we charge the customer?** And is VAT already inside it?

13. **How long is a quote good for?** If we quote at checkout and create the shipment an
    hour or a day later, do we pay the price we were quoted?

14. Our products have **weight but no dimensions**, so we'd send `IsVolumetric: false`.
    Is that fine, or will parcels get re-measured and re-priced at the centre? If they're
    re-priced, who covers the difference — because we've already charged the customer by
    then.

15. Should the weight we send be the **product weight or the packed weight** with box and
    filler?

16. Is **insurance mandatory**, and how is it worked out — a percentage of the declared
    value? Can we turn it off?

17. Is a **delivery ETA** available anywhere in the API? We need to show customers a
    delivery window at checkout and we can't find one in either the price or tracking
    response.

## Tracking

18. **Is there a webhook for status changes?** Your developer page mentions one but this API
    doc doesn't. If not, how often can we poll `/track/mobileShipment` per shipment?

19. Can you send the **full list of tracking `Status` codes**? The docs only show `MAHD`,
    `DLP` and `CRT` as examples. We specifically need to know which codes mean **delivered**,
    **failed** and **returned**, so we can update the order and email the customer correctly.

## Billing

20. I am not too sure how payment remittance are agreed between TokeCosmetics and GIG. Does
    `/create/dropOff` need a funded wallet balance to succeed, or is our account invoiced?
    If it needs a balance, **what error comes back when it runs out**, so we can alert
    ourselves before customer orders start failing.

21. Do you provide a **statement of shipments and charges** we can reconcile against our own
    records at settlement time — via API, or as a file?

## Operations

22. Can a shipment be **cancelled or amended** after `/create/dropOff`? We don't see a
    cancellation endpoint, and customers do change their minds.

23. What happens on a **failed delivery** — is it returned to us automatically, are we
    charged for the return, and how do we find out through the API?

24. Are there **test waybills in sandbox** we can use to walk through the full tracking
    lifecycle (created → in transit → delivered → failed) without shipping anything real?

---

Thanks. The four at the top are what's holding up our build — the rest we can work around
for now.
