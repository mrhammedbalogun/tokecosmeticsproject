from django.db import migrations

CURRENCIES = [
    # code, symbol, decimal_places
    ("NGN", "₦", 2),
    ("GBP", "£", 2),
    ("USD", "$", 2),
    ("CAD", "CA$", 2),
]

COUNTRIES = [
    # code, name, currency, is_default, is_rest_of_world, tax_rate, incl_tax
    ("NG", "Nigeria", "NGN", True, False, "7.50", True),
    ("GB", "United Kingdom", "GBP", False, False, "20.00", True),
    ("US", "United States", "USD", False, False, "0.00", False),
    ("CA", "Canada", "CAD", False, False, "0.00", False),
    ("ZZ", "International", "USD", False, True, "0.00", False),
]


def seed(apps, schema_editor):
    Currency = apps.get_model("core", "Currency")
    Country = apps.get_model("core", "Country")
    for code, symbol, dp in CURRENCIES:
        Currency.objects.update_or_create(
            code=code, defaults={"symbol": symbol, "decimal_places": dp, "is_active": True}
        )
    for code, name, cur, is_default, is_row, tax, incl in COUNTRIES:
        Country.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "currency_id": cur,
                "is_active": True,
                "is_default": is_default,
                "is_rest_of_world": is_row,
                "tax_rate_percent": tax,
                "prices_include_tax": incl,
            },
        )


def unseed(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    Currency = apps.get_model("core", "Currency")
    Country.objects.filter(code__in=[c[0] for c in COUNTRIES]).delete()
    Currency.objects.filter(code__in=[c[0] for c in CURRENCIES]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0002_currency_country")]
    operations = [migrations.RunPython(seed, unseed)]
