"""Maps a gateway code → instance. All gateways are registered UNCONDITIONALLY (even
without API keys) — adapters read keys lazily and raise GatewayNotConfigured at call
time, so an admin can enable a gateway per-country before its keys are deployed without
crashing imports, migrations, or unrelated tests."""
from apps.payments.gateways.bank_transfer import BankTransferGateway
from apps.payments.gateways.flutterwave import FlutterwaveGateway
from apps.payments.gateways.paypal import PayPalGateway
from apps.payments.gateways.paystack import PaystackGateway
from apps.payments.gateways.stripe_gateway import StripeGateway
from apps.payments.models import CountryPaymentGateway

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


def active_gateways_for(country) -> list[dict]:
    """Active CountryPaymentGateway rows for a country, in sort order."""
    rows = CountryPaymentGateway.objects.filter(country=country, is_active=True).order_by(
        "sort_order"
    )
    return [{"gateway": r.gateway, "sort_order": r.sort_order} for r in rows]
