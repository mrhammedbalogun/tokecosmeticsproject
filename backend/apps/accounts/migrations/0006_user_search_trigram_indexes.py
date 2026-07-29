"""Trigram indexes on the customer columns the admin search box matches (Plan-16 Task 6).

`TrigramExtension()` is repeated here even though `catalog/0004_product_name_trgm` already
runs it. Migration order across apps is only guaranteed where a dependency says so, and
depending on a catalog migration from `accounts` would be a strange edge to introduce for
one `CREATE EXTENSION`. The operation is `CREATE EXTENSION IF NOT EXISTS`, so on any
database that has already run catalog/0004 it is a no-op that needs no privilege.
"""
import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_stafftotp_staffrecoverycode'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name='user',
            index=django.contrib.postgres.indexes.GinIndex(django.contrib.postgres.indexes.OpClass(django.db.models.functions.text.Upper('email'), name='gin_trgm_ops'), name='user_email_trgm'),
        ),
        migrations.AddIndex(
            model_name='user',
            index=django.contrib.postgres.indexes.GinIndex(django.contrib.postgres.indexes.OpClass(django.db.models.functions.text.Upper('first_name'), name='gin_trgm_ops'), name='user_first_trgm'),
        ),
        migrations.AddIndex(
            model_name='user',
            index=django.contrib.postgres.indexes.GinIndex(django.contrib.postgres.indexes.OpClass(django.db.models.functions.text.Upper('last_name'), name='gin_trgm_ops'), name='user_last_trgm'),
        ),
        migrations.AddIndex(
            model_name='user',
            index=django.contrib.postgres.indexes.GinIndex(django.contrib.postgres.indexes.OpClass(django.db.models.functions.text.Upper('toke_id'), name='gin_trgm_ops'), name='user_toke_id_trgm'),
        ),
    ]
