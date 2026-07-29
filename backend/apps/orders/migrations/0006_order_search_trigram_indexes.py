"""Trigram indexes on the order columns admin search and the order queue match.

Plan-16 Task 6. `number` and `legacy_number` already carry btrees (UNIQUE and plain) and
neither helps: both lookups are unanchored `%term%`, which no btree can serve at any price.
See `TrigramExtension` note in `accounts/0006_user_search_trigram_indexes`.
"""
import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.conf import settings
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('checkout', '0001_initial'),
        ('core', '0006_auditlog_append_only'),
        ('orders', '0005_order_orders_orde_status_adb568_idx_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name='order',
            index=django.contrib.postgres.indexes.GinIndex(django.contrib.postgres.indexes.OpClass(django.db.models.functions.text.Upper('number'), name='gin_trgm_ops'), name='order_number_trgm'),
        ),
        migrations.AddIndex(
            model_name='order',
            index=django.contrib.postgres.indexes.GinIndex(django.contrib.postgres.indexes.OpClass(django.db.models.functions.text.Upper('legacy_number'), name='gin_trgm_ops'), name='order_legacy_num_trgm'),
        ),
        migrations.AddIndex(
            model_name='order',
            index=django.contrib.postgres.indexes.GinIndex(django.contrib.postgres.indexes.OpClass(django.db.models.functions.text.Upper('email'), name='gin_trgm_ops'), name='order_email_trgm'),
        ),
    ]
