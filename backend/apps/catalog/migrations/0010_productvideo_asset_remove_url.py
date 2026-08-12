# Hand-written, because makemigrations cannot add a NOT NULL column without asking what
# to put in existing rows — and the answer here is "there are none": ProductVideo shipped
# in 0003 and nothing (no importer, no admin surface, no storefront serializer) has ever
# created a row. Verified against production before writing this. Dropping `url` against
# an empty table is free; a populated one would have needed a data migration instead.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0009_catalog_search_trigram_indexes"),
        ("cms", "0007_mediaasset_banner_image_asset_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="productvideo",
            name="url",
        ),
        migrations.AddField(
            model_name="productvideo",
            name="asset",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="product_videos",
                to="cms.mediaasset",
            ),
        ),
    ]
