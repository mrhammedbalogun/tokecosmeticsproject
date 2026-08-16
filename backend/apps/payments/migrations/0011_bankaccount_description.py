from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payments", "0010_deactivate_uncertified_gateways"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankaccount",
            name="description",
            field=models.TextField(blank=True),
        ),
    ]
