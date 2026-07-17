"""Payment gateway contract. Plan-08 shipped bank_transfer; Plan-09 adds the four
networked gateways (Paystack, Flutterwave, Stripe, PayPal) behind this same ABC —
the interface was proven on the easy gateway before the hard ones.

The whole point of this boundary: callers (checkout, webhook processing, refunds)
never know or care whether an adapter uses raw httpx or an SDK, minor units or major,
a native webhook id or a derived one. Each adapter encapsulates its gateway's quirks.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings


# --- Exceptions -------------------------------------------------------------


class GatewayError(Exception):
    """Base for all gateway failures."""


class GatewayTimeout(GatewayError):
    """A gateway HTTP call timed out or the connection failed after retries."""


class GatewayNotConfigured(GatewayError):
    """A gateway was invoked without the API keys it needs (missing from settings).

    Surfaced to the API as 503 — fails safe when an admin enables a gateway in
    CountryPaymentGateway before its keys are deployed.
    """


class InvalidSignature(GatewayError):
    """A webhook payload failed signature verification — treat as hostile, do not process."""


class ManualVerificationOnly(GatewayError):
    """This gateway cannot be asked whether the money landed — a human must confirm it.

    A GatewayError subclass on purpose: callers already degrade gracefully on GatewayError
    ("couldn't verify right now, report current state"), which is exactly the right
    behaviour here, so no caller needs a special case. It is NOT the base `verify()`
    default — that stays NotImplementedError so a *networked* gateway which forgets to
    implement verify() fails loudly instead of silently declining to check for money.
    """


class ManualRefundOnly(GatewayError):
    """This gateway cannot push money back — a human sends the transfer and records it.

    A GatewayError (unlike the base refund()'s NotImplementedError) so create_refund's
    existing handler catches it, marks the reserved Refund row failed, and frees the
    amount instead of 500ing and wedging that payment's refundable balance forever.
    """


class VerificationMismatch(GatewayError):
    """gateway.verify() returned an amount/currency that does not match the order."""


# --- Result value objects ---------------------------------------------------


@dataclass(frozen=True)
class InitiateResult:
    # action tells the storefront what to do next:
    #   "bank_details" | "redirect" | "client_secret"
    action: str
    reference: str = ""
    data: dict = field(default_factory=dict)  # redirect_url / client_secret / bank details


@dataclass(frozen=True)
class VerifyResult:
    # status is normalized across gateways: "succeeded" | "pending" | "failed"
    status: str
    amount: Decimal            # major units, as the gateway reports the settled amount
    currency: str              # ISO code, e.g. "NGN"
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RefundResult:
    status: str                # "succeeded" | "pending" | "failed"
    gateway_reference: str = ""
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedEvent:
    event_id: str              # gateway's event id, or a derived-deterministic id (Flutterwave)
    event_type: str
    gateway_reference: str     # links the event back to a Payment
    raw: dict = field(default_factory=dict)
    # Which pipeline should handle this event. Each adapter classifies its own taxonomy,
    # because only it knows that (say) "charge.refunded" is a refund and not a payment.
    # Routing matters: sending a refund event through confirm_payment would re-verify an
    # already-refunded payment and mis-flag it as a double payment.
    kind: str = "payment"      # "payment" | "refund" | "other"
    refund_reference: str = "" # the gateway's refund id, when the event carries one


# --- The contract -----------------------------------------------------------


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

    @abstractmethod
    def initiate(self, payment, order, return_url: str = "") -> InitiateResult:
        """Create the payment intent/transaction at the gateway and tell the storefront
        how to collect the money. Raises GatewayNotConfigured if keys are missing."""

    def verify(self, payment) -> VerifyResult:
        """Server-side re-verification. ALWAYS called before fulfilling — the webhook
        body is never trusted for money. Overridden by networked gateways (Plan-09)."""
        raise NotImplementedError

    def refund(self, payment, amount: Decimal, reason: str = "") -> RefundResult:
        raise NotImplementedError

    def parse_webhook(self, request) -> ParsedEvent:
        """Verify the signature over the RAW request body and return the parsed event.
        Raises InvalidSignature if the signature does not check out."""
        raise NotImplementedError
