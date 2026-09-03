"""Move combo images under `catalog/`, where the CDN can actually serve them.

`Combo.image` shipped as `upload_to="combos/"`. The object uploaded fine and then 403'd
at CloudFront, because the bucket is PRIVATE (the nightly Postgres dumps share it, under
`backups/`) and the Origin Access Control policy is scoped to `catalog/*` on purpose.
Every other upload in this project already lives under that prefix — `apps/cms` writes
its banners to `catalog/cms-banners/` for exactly this reason.

The `AlterField` alone would only redirect FUTURE uploads and leave every image already
saved pointing at an unreachable key, so the data step relocates them.
"""
from django.core.files.storage import default_storage
from django.db import migrations, models

OLD_PREFIX = "combos/"
NEW_PREFIX = "catalog/combos/"


def _relocate(apps, schema_editor):
    """Copy each stray object under the new prefix and repoint the row.

    COPY-THEN-REPOINT, and the old object is deliberately NOT deleted. A migration that
    moves bytes it cannot roll back is a migration that loses an image if the deploy is
    reverted; the strays are a handful of files and can be swept by hand once this has
    been live for a while. `infra/aws/incoming-lifecycle.json` is where a rule would go
    if that is ever worth automating.

    Silent on failure per row. A storage backend that cannot read one object must not
    take the whole deploy down with it — the row simply keeps its old name and shows the
    same broken thumbnail it already shows, which is no worse than before this ran.
    """
    Combo = apps.get_model("combos", "Combo")
    for combo in Combo.objects.exclude(image="").exclude(image=None).iterator():
        name = combo.image.name or ""
        if not name.startswith(OLD_PREFIX):
            continue
        target = NEW_PREFIX + name[len(OLD_PREFIX):]
        try:
            if not default_storage.exists(target):
                with default_storage.open(name, "rb") as fh:
                    # `save` may return a suffixed name if something already sits there;
                    # trust what it returns rather than what was asked for.
                    target = default_storage.save(target, fh)
            combo.image = target
            combo.save(update_fields=["image"])
        except Exception:  # noqa: BLE001 — see the docstring
            continue


def _unrelocate(apps, schema_editor):
    """Point the rows back at the original keys, which were never deleted."""
    Combo = apps.get_model("combos", "Combo")
    for combo in Combo.objects.exclude(image="").exclude(image=None).iterator():
        name = combo.image.name or ""
        if name.startswith(NEW_PREFIX):
            combo.image = OLD_PREFIX + name[len(NEW_PREFIX):]
            combo.save(update_fields=["image"])


class Migration(migrations.Migration):

    dependencies = [
        ("combos", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="combo",
            name="image",
            field=models.ImageField(
                blank=True, max_length=500, null=True, upload_to="catalog/combos/"
            ),
        ),
        migrations.RunPython(_relocate, _unrelocate),
    ]
