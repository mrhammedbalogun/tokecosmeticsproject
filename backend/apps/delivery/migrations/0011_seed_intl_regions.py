"""Level-1 regions for the non-NG markets (Countries_breakdown mapping).

GB: 4 constituent countries. US: 50 states + DC. CA: 10 provinces + 3 territories.
Level 2 (counties / municipalities / districts) is deliberately NOT seeded: abroad,
carriers price by postcode/ZIP zone rather than administrative subdivision, and a
bulk seed of ~7,000 rows nobody prices by would only slow the pickers down. The
hierarchy machinery (matcher ancestor-walk, parent-child region browse) is already
generic, so Level-2 rows can be added per-country the day a price actually differs
by one.
"""
import json
from pathlib import Path

from django.conf import settings
from django.db import migrations

FIXTURE = Path(settings.BASE_DIR) / "apps" / "core" / "fixtures" / "intl_level1_regions.json"


def seed(apps, schema_editor):
    Region = apps.get_model("core", "Region")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for country_code, names in data.items():
        for name in names:
            Region.objects.get_or_create(
                country_code=country_code, parent=None, name=name,
                defaults={"level": "state"},
            )


def unseed(apps, schema_editor):
    Region = apps.get_model("core", "Region")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for country_code, names in data.items():
        Region.objects.filter(
            country_code=country_code, parent=None, name__in=names
        ).delete()


class Migration(migrations.Migration):
    dependencies = [("delivery", "0010_seed_gig_pickup_option")]
    operations = [migrations.RunPython(seed, unseed)]
