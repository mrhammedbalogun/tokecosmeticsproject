# Seed the GIG carrier option (Plan-32a slice 3) — INACTIVE. It ships dark and is
# flipped on by the go-live runbook once production credentials exist, coverage has
# been re-synced against production, and the wallet is funded. The price column is
# unused for carrier options (the live quote is the price); min/max days are the
# customer-facing ETA and admin-editable.

from django.db import migrations


def seed_gig_option(apps, schema_editor):
    DeliveryOption = apps.get_model("delivery", "DeliveryOption")
    Country = apps.get_model("core", "Country")
    Currency = apps.get_model("core", "Currency")
    if DeliveryOption.objects.filter(carrier_code="gig").exists():
        return
    ngn = Currency.objects.filter(code="NGN").first()
    ng = Country.objects.filter(code="NG").first()
    if ngn is None or ng is None:  # cannot happen after core 0003, but never crash a deploy
        return
    option = DeliveryOption.objects.create(
        name="Door Delivery (GIG)",
        kind="carrier",
        carrier_code="gig",
        price=0,
        currency=ngn,
        quote_required=False,
        min_days=1,
        max_days=5,
        is_active=False,
        sort=5,
    )
    option.countries.add(ng)


def unseed(apps, schema_editor):
    apps.get_model("delivery", "DeliveryOption").objects.filter(carrier_code="gig").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0005_giglga"),
        ("core", "0003_seed_countries_currencies"),
    ]
    operations = [migrations.RunPython(seed_gig_option, unseed)]
