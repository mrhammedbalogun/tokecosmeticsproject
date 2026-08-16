from django.db import migrations


class Migration(migrations.Migration):
    """0011 added `description` (checkout copy) beside `instructions` mirroring Woo's
    two-field split; the owner's verdict after one release was one rich-text
    `instructions` field behind a read-instructions link. No prod row ever held a
    description (the table was empty at both deploys), so this is a clean drop."""

    dependencies = [
        ("payments", "0011_bankaccount_description"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="bankaccount",
            name="description",
        ),
    ]
