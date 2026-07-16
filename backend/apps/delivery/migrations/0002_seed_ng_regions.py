import json
from pathlib import Path

from django.conf import settings
from django.db import migrations

FIXTURE = Path(settings.BASE_DIR) / "apps" / "core" / "fixtures" / "ng_regions.json"


def seed(apps, schema_editor):
    Region = apps.get_model("core", "Region")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for state_name, lgas in data.items():
        state, _ = Region.objects.get_or_create(
            country_code="NG", parent=None, name=state_name,
            defaults={"level": "state"},
        )
        for lga_name in lgas:
            Region.objects.get_or_create(
                country_code="NG", parent=state, name=lga_name,
                defaults={"level": "area"},
            )


def unseed(apps, schema_editor):
    apps.get_model("core", "Region").objects.filter(country_code="NG").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("delivery", "0001_initial"),
        ("core", "0001_initial"),  # core.Region is created in core's initial migration
    ]
    operations = [migrations.RunPython(seed, unseed)]
