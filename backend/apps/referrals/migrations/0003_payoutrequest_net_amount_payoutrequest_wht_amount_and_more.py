"""Withholding fields on PayoutRequest, all zero by ruling — plus the backfill that
stops every payout ever made from reading as "net zero".

`net_amount` defaults to 0 at the column level because a NOT NULL add needs a default,
and 0 is wrong for every row that already exists: no deduction was ever taken from them,
so their net IS their gross. Without the backfill below, three real payouts in production
and every dev row would claim the shop sent nothing.
"""
from django.db import migrations, models


def backfill_net_equals_gross(apps, schema_editor):
    """Every existing payout was paid in full — set net to match, leave WHT at zero."""
    PayoutRequest = apps.get_model("referrals", "PayoutRequest")
    PayoutRequest.objects.update(net_amount=models.F("amount"))


class Migration(migrations.Migration):

    dependencies = [
        ('referrals', '0002_alter_commission_payout_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='payoutrequest',
            name='net_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='payoutrequest',
            name='wht_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='payoutrequest',
            name='wht_rate_percent',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name='payoutrequest',
            name='wht_remittance_reference',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='payoutrequest',
            name='wht_remitted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        # Reverse is a no-op: dropping the columns is what un-applies this, and there is
        # nothing to restore into a column that will not exist.
        migrations.RunPython(backfill_net_equals_gross, migrations.RunPython.noop),
    ]
