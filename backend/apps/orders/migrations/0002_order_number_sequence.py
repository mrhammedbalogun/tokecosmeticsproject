from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("orders", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE IF NOT EXISTS order_number_seq START WITH 100001;",
            reverse_sql="DROP SEQUENCE IF EXISTS order_number_seq;",
        )
    ]
