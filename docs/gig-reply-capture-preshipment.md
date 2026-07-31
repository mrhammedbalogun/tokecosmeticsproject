# Reply to GIG — after studying `/capture/preshipment`

**To send.** Short on purpose: they asked us to study one endpoint and respond, not to
re-send 24 questions.

---

Thank you — reading `/capture/preshipment` answered several of our questions on its own, so
that was the right thing to point us at.

Three things it settled for us:

1. It returns a **Waybill** directly, so our biggest concern disappears. We had been looking
   at `/create/dropOff`, which returns a `TempCode`, while `/track/mobileShipment` and
   `/invoice/generate` both need a Waybill — we could not see how to get from one to the other.
2. **`ReceiverStationId` is optional** here. We had assumed we would need to map all 774
   Nigerian LGAs onto your station list ourselves. If you resolve the station from the
   coordinates, that work goes away entirely.
3. Coverage becomes a pricing call rather than a separate lookup, which is simpler for us.

**The one thing it creates for us is coordinates.** We are a web store: a customer types an
address at checkout — state, LGA, street — and we never capture latitude or longitude.
`SenderLocation` and `ReceiverLocation` are both required, so this is the piece we cannot
satisfy today.

So, three questions, and the second is the one that decides our build:

**1. Is `/capture/preshipment` the flow you recommend for an e-commerce merchant?**
If so, what is the DropOff flow intended for — a different kind of arrangement?

**2. Can a shipment be priced and created from a STRUCTURED ADDRESS — state, LGA, street —
rather than coordinates?** For example by sending `ReceiverStationId` and
`DestinationServiceCenterId` and omitting `ReceiverLocation`. If that works, we can ship
quickly. If not, we will add address geocoding, which is a larger change on our side.

**3. If coordinates are required, what precision do you need?** Would an LGA-level centre
point price correctly, or does it need to be the actual door? We ask because address quality
varies a great deal here, and we would rather know now than discover it in the pricing.

Two smaller ones, whenever convenient:

- **`VehicleType` is required on `/capture/preshipment`.** For a small cosmetics parcel —
  typically under 1 kg — which value should we send?
- **How is our account billed?** We plan to settle with you manually, weekly or biweekly. We
  only need to know whether `/capture/preshipment` requires a funded wallet balance to
  succeed, so that we can alert ourselves before customer orders start failing.

Thank you again.
