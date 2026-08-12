"""Maps a gateway code → instance. All gateways are registered UNCONDITIONALLY (even
without API keys) — adapters read keys lazily and raise GatewayNotConfigured at call
time, so an admin can enable a gateway per-country before its keys are deployed without
crashing imports, migrations, or unrelated tests."""
from apps.payments.gateways.bank_transfer import BankTransferGateway
from apps.payments.gateways.flutterwave import FlutterwaveGateway
from apps.payments.gateways.paypal import PayPalGateway
from apps.payments.gateways.paystack import PaystackGateway
from apps.payments.gateways.stripe_gateway import StripeGateway
from apps.payments.checks import missing_settings_for
from apps.payments.models import BankAccount, CountryPaymentGateway

_REGISTRY = {
    BankTransferGateway.code: BankTransferGateway(),
    PaystackGateway.code: PaystackGateway(),
    StripeGateway.code: StripeGateway(),
    FlutterwaveGateway.code: FlutterwaveGateway(),
    PayPalGateway.code: PayPalGateway(),
}


class UnknownGateway(Exception):
    pass


def get_gateway(code: str):
    try:
        return _REGISTRY[code]
    except KeyError as exc:
        raise UnknownGateway(code) from exc


def _is_configured(gateway: str, country) -> bool:
    """Can this gateway actually take a payment for this country right now?

    Bank transfer needs no API keys -- it needs an ACCOUNT, and checkout refuses
    the order at initiate when there isn't one. Same failure shape as a missing
    secret, so it is answered here too.

    Currency is part of the same question (2026-08-12, dynamic market settings):
    a gateway that cannot charge the market's currency would render a button
    that 503s at initiate -- e.g. Paystack switched on in GB. An adapter with no
    supported_currencies (bank transfer) has no restriction. An unknown code
    (the model's gateway field is free text) can never be offered.
    """
    adapter = _REGISTRY.get(gateway)
    if adapter is None:
        return False
    supported = getattr(adapter, "supported_currencies", None)
    if supported and country.currency_id not in supported:
        return False
    if gateway == "bank_transfer":
        return BankAccount.objects.filter(country=country, is_active=True).exists()
    return not missing_settings_for(gateway)


def active_gateways_for(country) -> list[dict]:
    """Gateways offerable to this country right now, in sort order.

    `is_active` is merchandising intent -- a human toggle saying "we want to
    sell with this". It is NOT permission, and must never be the last line of
    defence: a row switched on before its keys are deployed (or a deploy that
    loses an env var) would otherwise hand the customer a gateway that 503s at
    initiate. So intent is intersected with configuredness on every request.

    Consequence worth knowing: an env-var mishap silently NARROWS the payment
    menu instead of erroring. That is the right trade -- a shorter menu beats a
    stranded customer -- and payments.W001/W002 are the alarm that says intent
    and reality have diverged. A thin menu is the symptom; check the warnings.
    """
    rows = CountryPaymentGateway.objects.filter(country=country, is_active=True).order_by(
        "sort_order"
    )
    return [
        {"gateway": r.gateway, "sort_order": r.sort_order}
        for r in rows
        if _is_configured(r.gateway, country)
    ]
