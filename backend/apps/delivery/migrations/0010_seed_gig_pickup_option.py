# Plan-32b slice 1: name the existing GIG row's service and seed the pickup row, DARK.
from django.db import migrations


def seed(apps, schema_editor):
    DeliveryOption = apps.get_model("delivery", "DeliveryOption")
    Country = apps.get_model("core", "Country")
    DeliveryOption.objects.filter(carrier_code="gig", carrier_service="").update(
        carrier_service="home"
    )
    if DeliveryOption.objects.filter(carrier_code="gig", carrier_service="pickup").exists():
        return
    home = DeliveryOption.objects.filter(carrier_code="gig", carrier_service="home").first()
    ng = Country.objects.filter(code="NG").first()
    if home is None or ng is None:
        return
    pickup = DeliveryOption.objects.create(
        name="Pickup at GIG Centre", kind="carrier", carrier_code="gig",
        carrier_service="pickup", price=0, currency=home.currency,
        quote_required=False, min_days=home.min_days, max_days=home.max_days,
        is_active=False, sort=home.sort + 1,
    )
    pickup.countries.add(ng)


def unseed(apps, schema_editor):
    apps.get_model("delivery", "DeliveryOption").objects.filter(
        carrier_code="gig", carrier_service="pickup"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("delivery", "0009_gigcentre")]
    operations = [migrations.RunPython(seed, unseed)]
