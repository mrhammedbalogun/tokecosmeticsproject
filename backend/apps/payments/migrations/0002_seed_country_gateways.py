from django.db import migrations

SEED = {
    "NG": [("paystack", 1), ("flutterwave", 2), ("bank_transfer", 3)],
    "GB": [("stripe", 1), ("paypal", 2)],
    "US": [("stripe", 1), ("paypal", 2)],
    "CA": [("stripe", 1), ("paypal", 2)],
    "ZZ": [("stripe", 1), ("paypal", 2)],
}


def seed(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    CPG = apps.get_model("payments", "CountryPaymentGateway")
    for code, gateways in SEED.items():
        country = Country.objects.filter(code=code).first()
        if not country:
            continue
        for gateway, sort in gateways:
            CPG.objects.get_or_create(
                country=country, gateway=gateway,
                defaults={"is_active": True, "sort_order": sort},
            )


def unseed(apps, schema_editor):
    apps.get_model("payments", "CountryPaymentGateway").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("payments", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
