# Seed the AAJ carrier option (Plan-43) — INACTIVE, exactly as GIG's 0006 did. It
# ships dark and is flipped on by the go-live runbook once the production API key and
# account number are in the env, one controlled live booking has been processed, and
# AAJ_PROCESS_ENABLED is on. The price column is unused for carrier options (the live
# quote is the price); min/max days are the customer-facing ETA fallback — carriers.py
# replaces them with AAJ's own per-state figure whenever the quote carries one.

from django.db import migrations


def seed_aaj_option(apps, schema_editor):
    DeliveryOption = apps.get_model("delivery", "DeliveryOption")
    Country = apps.get_model("core", "Country")
    Currency = apps.get_model("core", "Currency")
    if DeliveryOption.objects.filter(carrier_code="aaj").exists():
        return
    ngn = Currency.objects.filter(code="NGN").first()
    ng = Country.objects.filter(code="NG").first()
    if ngn is None or ng is None:  # cannot happen after core 0003, but never crash a deploy
        return
    option = DeliveryOption.objects.create(
        name="Door Delivery (AAJ Express)",
        kind="carrier",
        carrier_code="aaj",
        carrier_service="home",
        price=0,
        currency=ngn,
        quote_required=False,
        min_days=2,
        max_days=8,
        is_active=False,
        sort=6,
    )
    option.countries.add(ng)


def unseed(apps, schema_editor):
    apps.get_model("delivery", "DeliveryOption").objects.filter(carrier_code="aaj").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0021_aajshipment"),
        ("core", "0003_seed_countries_currencies"),
    ]
    operations = [migrations.RunPython(seed_aaj_option, unseed)]
