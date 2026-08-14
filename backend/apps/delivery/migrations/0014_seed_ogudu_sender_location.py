# Plan-34: the current env-var sender becomes row #1, so selection is identical
# before and after deploy. Values are the CONFIRMED production ones (Hammed,
# 2026-08-14 — "Ogudu Mall is correct, keep it"), hardcoded rather than read from
# settings: a migration must write the same row on every machine, and dev
# settings default to the old Gbagada placeholder. Abuja is DATA ENTRY via the
# admin, never a migration.
from django.db import migrations


def seed(apps, schema_editor):
    SenderLocation = apps.get_model("delivery", "SenderLocation")
    if SenderLocation.objects.exists():
        return
    SenderLocation.objects.create(
        name="Ogudu Mall (Lagos)",
        phone="+2347074800702",
        address="Shop No 1, Ogudu Mall, Kosofe, Ogudu, Lagos",
        locality="Ogudu",
        # 6 dp = the column's precision (~10 cm); the prod env pin's 7th decimal
        # is below what GPS or GIG's pricing can distinguish.
        latitude="6.576522",
        longitude="3.389387",
        is_active=True,
    )


def unseed(apps, schema_editor):
    apps.get_model("delivery", "SenderLocation").objects.filter(
        name="Ogudu Mall (Lagos)"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("delivery", "0013_senderlocation_gigshipment_origin")]
    operations = [migrations.RunPython(seed, unseed)]
