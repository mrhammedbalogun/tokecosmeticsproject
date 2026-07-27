"""Switch off the gateways 0009 reactivated without certification.

Plan-09b's standing rule: a networked gateway does not reactivate without a
driven test-mode payment. Only Paystack has earned that (Plan-14b, Tasks 16-17).
0009 nonetheless turned on paystack, flutterwave AND paypal in one pass,
reasoning that test-mode keys and an un-cut-over storefront made it safe. That
reasoning covered the blast radius, not the rule -- and it left production
offering two gateways with no credentials at all, which 503 at initiate.

This restores the menu to what is actually certified and configured:
NG = paystack + bank_transfer, everywhere else = bank_transfer.

Reverse is a deliberate NO-OP. Reactivating a gateway is a human checkpoint
that must follow a real test-mode payment; it is never a rollback side effect.
0009 got that convention right in its own reverse, and unmigrating past this
point must not silently hand customers a broken PayPal button.

Note this is defence in depth, not the guarantee: `active_gateways_for` also
filters on configuredness at request time, so these gateways could not be
offered even if someone flipped is_active back on by hand. This migration makes
the database state honest; the registry makes being wrong harmless.
"""
from django.db import migrations

UNCERTIFIED = ["flutterwave", "paypal"]


def deactivate(apps, schema_editor):
    CPG = apps.get_model("payments", "CountryPaymentGateway")
    CPG.objects.filter(gateway__in=UNCERTIFIED).update(is_active=False)


def noop(apps, schema_editor):
    """Intentionally does nothing -- see the module docstring."""


class Migration(migrations.Migration):
    dependencies = [("payments", "0009_reactivate_online_gateways")]
    operations = [migrations.RunPython(deactivate, noop)]
