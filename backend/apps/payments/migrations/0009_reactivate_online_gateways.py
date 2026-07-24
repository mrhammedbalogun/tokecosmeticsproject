"""Reactivate the hybrid online gateways for Plan-14b test-mode certification.

0007 turned every networked gateway off and set bank_transfer to sort 1 everywhere. This
restores the real menu: Paystack/Flutterwave on NG, PayPal internationally, bank transfer
as the fallback. Stripe stays OFF (dropped in Plan-14). Safe: keys are test-mode and the
production storefront is not cut over — going live is a separate gated step (Plan-27).

Reverse switches the online gateways back off and restores bank_transfer to sort 1 (the
0007 end-state): reactivating a gateway is a human checkpoint, never a rollback side effect.

Numbering note: this task was specced assuming 0007_launch_bank_transfer_only was the
latest payments migration (making this 0008). By execution time, 0008_payment_purpose
(adding Payment.purpose, unrelated to gateway menus) had already landed on top of 0007.
This migration is therefore 0009 and depends on 0008_payment_purpose instead.
"""
from django.db import migrations

MENU = {
    "NG": [("paystack", 1), ("flutterwave", 2), ("bank_transfer", 3)],
    "GB": [("paypal", 1), ("bank_transfer", 2)],
    "US": [("paypal", 1), ("bank_transfer", 2)],
    "CA": [("paypal", 1), ("bank_transfer", 2)],
    "ZZ": [("paypal", 1), ("bank_transfer", 2)],
}
ONLINE = ["paystack", "flutterwave", "paypal"]


def reactivate(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    CPG = apps.get_model("payments", "CountryPaymentGateway")
    for code, rows in MENU.items():
        country_id = Country.objects.filter(code=code).values_list("pk", flat=True).first()
        if country_id is None:
            continue
        for gateway, sort in rows:
            # country_id=, not country=<instance>: assigning a historical model instance
            # to a relation triggers Django's cross-app type check, which can reject it as
            # "not a Country instance" when this RunPython is replayed as part of a
            # multi-step migrate (e.g. reversing several migrations in one executor.migrate()
            # call) — the FK's related-model snapshot and the instance's own snapshot can
            # come from different rendered ProjectStates even though both represent "core.Country".
            # Filtering by the raw id sidesteps that check entirely.
            CPG.objects.update_or_create(
                country_id=country_id, gateway=gateway,
                defaults={"is_active": True, "sort_order": sort},
            )


def deactivate(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    CPG = apps.get_model("payments", "CountryPaymentGateway")
    CPG.objects.filter(gateway__in=ONLINE).update(is_active=False)
    for code in MENU:
        country_id = Country.objects.filter(code=code).values_list("pk", flat=True).first()
        if country_id is None:
            continue
        CPG.objects.update_or_create(
            country_id=country_id, gateway="bank_transfer",
            defaults={"is_active": True, "sort_order": 1},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0008_payment_purpose"),
        ("core", "0003_seed_countries_currencies"),
    ]
    operations = [migrations.RunPython(reactivate, deactivate)]
