from decimal import Decimal

from django.db import migrations


def seed(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    Currency = apps.get_model("core", "Currency")
    Region = apps.get_model("core", "Region")
    Option = apps.get_model("delivery", "DeliveryOption")

    def cur(code):
        return Currency.objects.filter(code=code).first()

    # Guard: skip cleanly if countries/currencies aren't seeded (fresh test DBs).
    ng = Country.objects.filter(code="NG").first()
    if ng and cur("NGN"):
        nationwide = Option.objects.create(
            name="Nationwide Delivery", kind="manual", price=Decimal("3500.00"),
            currency=cur("NGN"), min_days=2, max_days=5, sort=10,
        )
        nationwide.countries.add(ng)
        lagos = Region.objects.filter(country_code="NG", level="state", name="Lagos").first()
        if lagos:
            lagos_opt = Option.objects.create(
                name="Lagos Delivery", kind="manual", price=Decimal("1500.00"),
                currency=cur("NGN"), min_days=1, max_days=2, sort=1,
            )
            lagos_opt.regions.add(lagos)

    for code, ccy, price in [("GB", "GBP", "6.00"), ("US", "USD", "12.00"),
                             ("CA", "CAD", "15.00"), ("ZZ", "USD", "25.00")]:
        country = Country.objects.filter(code=code).first()
        if country and cur(ccy):
            opt = Option.objects.create(
                name=f"{country.name} Standard", kind="manual", price=Decimal(price),
                currency=cur(ccy), min_days=3, max_days=10, sort=20,
            )
            opt.countries.add(country)


def unseed(apps, schema_editor):
    apps.get_model("delivery", "DeliveryOption").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("delivery", "0002_seed_ng_regions")]
    operations = [migrations.RunPython(seed, unseed)]
