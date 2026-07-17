"""Startup visibility: which payment gateways actually have keys?

On a solo project the failure mode is "deployed but forgot the Flutterwave secret", and
you find out when a customer can't pay. This surfaces it as a deploy-time warning
instead. It is a WARNING, not an ERROR, on purpose: an unconfigured gateway is a valid
state (adapters raise GatewayNotConfigured -> 503), and dev/CI shouldn't be blocked.
"""
from django.conf import settings
from django.core.checks import Warning, register
from django.db.utils import OperationalError, ProgrammingError

GATEWAY_REQUIRED_SETTINGS = {
    "paystack": ["PAYSTACK_SECRET_KEY"],
    "flutterwave": ["FLUTTERWAVE_SECRET_KEY", "FLUTTERWAVE_SECRET_HASH"],
    "stripe": ["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"],
    "paypal": ["PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID"],
}


def missing_settings_for(gateway: str) -> list[str]:
    return [
        name for name in GATEWAY_REQUIRED_SETTINGS.get(gateway, [])
        if not getattr(settings, name, "")
    ]


@register()
def gateway_configuration_check(app_configs, **kwargs):
    issues = []
    for gateway in sorted(GATEWAY_REQUIRED_SETTINGS):
        missing = missing_settings_for(gateway)
        if missing:
            issues.append(
                Warning(
                    f"Payment gateway '{gateway}' is not configured "
                    f"(missing: {', '.join(missing)}).",
                    hint=(
                        f"Customers whose country has '{gateway}' active in "
                        f"CountryPaymentGateway will get a 503 at checkout. Either set the "
                        f"env vars or deactivate the gateway for those countries."
                    ),
                    id="payments.W001",
                )
            )

    # Bank transfer needs no API keys — it needs an ACCOUNT. Same failure shape as a
    # missing secret: live for a country, unusable in practice. Checkout now refuses such
    # an order outright, so a stranded market cannot sell at all.
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

    return issues
