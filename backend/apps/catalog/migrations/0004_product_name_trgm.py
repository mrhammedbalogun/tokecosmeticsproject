import django.contrib.postgres.indexes
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("catalog", "0003_productimage_productvideo")]

    operations = [
        TrigramExtension(),  # CREATE EXTENSION pg_trgm — must run before the trigram index
        migrations.AddIndex(
            model_name="product",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["name"], name="product_name_trgm", opclasses=["gin_trgm_ops"]
            ),
        ),
    ]
