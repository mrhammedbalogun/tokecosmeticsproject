from django.db import migrations

# name, location, priority, [served country codes]
WAREHOUSES = [
    ("Lagos HQ", "NG", 1, ["NG", "ZZ"]),
    ("UK Warehouse", "GB", 1, ["GB", "US", "CA", "ZZ"]),
]


def seed(apps, schema_editor):
    Warehouse = apps.get_model("inventory", "Warehouse")
    Country = apps.get_model("core", "Country")
    for name, loc, priority, codes in WAREHOUSES:
        w, _ = Warehouse.objects.update_or_create(
            name=name, defaults={"location_country": loc, "priority": priority, "is_active": True}
        )
        w.serves_countries.set(Country.objects.filter(code__in=codes))


def unseed(apps, schema_editor):
    Warehouse = apps.get_model("inventory", "Warehouse")
    Warehouse.objects.filter(name__in=[w[0] for w in WAREHOUSES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        ("core", "0003_seed_countries_currencies"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
