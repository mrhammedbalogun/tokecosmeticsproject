from django.db import migrations

# The line's name at checkout / on emails, per market. `charge_tax` is left at its
# model default (True) everywhere: rates are unchanged by this migration, so nothing
# about what customers pay moves — US/CA/ZZ keep charging nothing via their 0% rate.
LABELS = {
    "NG": "VAT",
    "GB": "VAT",
    "US": "Sales Tax",
    "CA": "Sales Tax",
    "ZZ": "Tax",
}


def seed(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    StoreSettings = apps.get_model("core", "StoreSettings")
    for code, label in LABELS.items():
        Country.objects.filter(code=code).update(tax_label=label)
    # Create the singleton now rather than on first read, so the admin page has a row
    # to PATCH the moment this deploys.
    StoreSettings.objects.get_or_create(pk=1)


def unseed(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    Country.objects.filter(code__in=LABELS).update(tax_label="Tax")


class Migration(migrations.Migration):
    dependencies = [("core", "0009_storesettings_country_charge_tax_and_more")]
    operations = [migrations.RunPython(seed, unseed)]
