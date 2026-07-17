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
