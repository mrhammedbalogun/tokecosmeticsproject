"""Maps a gateway code → instance. Plan-09 registers paystack/flutterwave/stripe/paypal."""
from apps.payments.gateways.bank_transfer import BankTransferGateway
from apps.payments.models import CountryPaymentGateway

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
    rows = CountryPaymentGateway.objects.filter(country=country, is_active=True).order_by(
        "sort_order"
    )
    return [{"gateway": r.gateway, "sort_order": r.sort_order} for r in rows]
