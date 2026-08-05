"""Per-country label for the FIRST region level, mirroring `area_label` (0004).

The Countries_breakdown doc's mapping: Level 1 is a State (NG, US), a Province (CA)
or a Constituent Country (GB); Level 2 is an LGA / County / Municipality / District.
One row per country carries both labels so the admin wizard and the storefront
address form can name the levels without a redeploy per market.
"""
from django.db import migrations, models

LABELS = {
    # code: (state_label, area_label)
    "NG": ("State", "LGA"),
    "GB": ("Country", "District"),
    "US": ("State", "County"),
    "CA": ("Province", "Municipality"),
}


def seed(apps, schema_editor):
    Country = apps.get_model("core", "Country")
    for code, (state_label, area_label) in LABELS.items():
        Country.objects.filter(code=code).update(
            state_label=state_label, area_label=area_label
        )


def unseed(apps, schema_editor):
    pass  # the labels are display strings; leaving them set is harmless on rollback


class Migration(migrations.Migration):
    dependencies = [("core", "0007_region_centroid")]
    operations = [
        migrations.AddField(
            model_name="country",
            name="state_label",
            field=models.CharField(default="State", max_length=30),
        ),
        migrations.RunPython(seed, unseed),
    ]
