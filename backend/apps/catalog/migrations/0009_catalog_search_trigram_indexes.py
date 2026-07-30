"""`UPPER(...)` trigram indexes for `icontains` on product name and variant SKU.

Plan-16 Task 6. The extension is already created by `0004_product_name_trgm`, which this
migration transitively depends on, so no `TrigramExtension()` is needed here.

The existing `product_name_trgm` index is deliberately NOT replaced: it indexes the bare
column, which is what the storefront's `TrigramSimilarity` ranking uses, while `icontains`
compiles to `UPPER(name::text) LIKE ...` and needs the expression form. Two lookups, two
expressions, two indexes.
"""
import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('catalog', '0008_alter_brand_logo_alter_category_image_and_more'),
        ('core', '0006_auditlog_append_only'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='product',
            index=django.contrib.postgres.indexes.GinIndex(django.contrib.postgres.indexes.OpClass(django.db.models.functions.text.Upper('name'), name='gin_trgm_ops'), name='product_name_upper_trgm'),
        ),
        migrations.AddIndex(
            model_name='productvariant',
            index=django.contrib.postgres.indexes.GinIndex(django.contrib.postgres.indexes.OpClass(django.db.models.functions.text.Upper('sku'), name='gin_trgm_ops'), name='variant_sku_trgm'),
        ),
    ]
