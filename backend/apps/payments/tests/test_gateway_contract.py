from django.test import override_settings

from apps.payments.gateways.registry import _REGISTRY, get_gateway


def test_only_bank_transfer_is_manually_confirmed():
    manual = {code for code, g in _REGISTRY.items() if g.confirmation == "manual"}
    assert manual == {"bank_transfer"}


@override_settings(RESERVATION_TTL_MINUTES=17)
def test_networked_gateways_follow_the_setting_at_call_time():
    # A class-body `= settings.X` would freeze at import and ignore this.
    assert get_gateway("paystack").reservation_ttl_minutes == 17


@override_settings(RESERVATION_TTL_MINUTES=17)
def test_bank_transfer_holds_stock_for_24_hours_regardless():
    # A transfer waits on staff working hours; 30 minutes would expire every order before
    # the money could possibly be confirmed. Not tunable by the card setting.
    assert get_gateway("bank_transfer").reservation_ttl_minutes == 1440
