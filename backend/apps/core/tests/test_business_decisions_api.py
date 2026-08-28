"""The Business Decisions surface (2026-08-27): the two referral percentages.

`decisions.manage` — Owner AND Manager, deliberately one notch WIDER than the tax
screens next door, which are `settings.manage` and Owner-only. Tax is a legal position;
the commission rate and the referred customer's discount are a commercial one, and the
Manager is who makes it. The scope matrix itself is asserted in test_admin_role_matrix.py.
"""
from decimal import Decimal
from unittest import mock

import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.core.models import AuditLog, BusinessDecisions

pytestmark = pytest.mark.django_db

URL = "/api/v1/admin/business-decisions/"


@pytest.fixture
def owner():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


@pytest.fixture
def manager():
    c = APIClient()
    c.force_authenticate(user=staff_user(email="manager@toke.test", role="Manager"))
    return c


@pytest.fixture
def support():
    c = APIClient()
    c.force_authenticate(user=staff_user(email="support@toke.test", role="Support"))
    return c


# ── who may open it ──────────────────────────────────────────────────────────────────


def test_it_requires_staff():
    assert APIClient().get(URL).status_code in (401, 403)


def test_the_manager_holds_it_unlike_the_tax_screens(manager):
    """The point of the separate scope. A Manager is refused `/admin/tax/settings/` and
    allowed here, and that difference is the whole reason `decisions.manage` exists."""
    assert manager.get("/api/v1/admin/tax/settings/").status_code == 403
    assert manager.get(URL).status_code == 200


def test_support_cannot_read_or_write_it(support):
    """The desk answers "where is my commission?"; it does not set the rate."""
    assert support.get(URL).status_code == 403
    assert support.patch(
        URL, {"referrer_commission_percent": "1.00"}, format="json"
    ).status_code == 403


# ── reading and writing ──────────────────────────────────────────────────────────────


def test_the_first_read_creates_the_row_at_the_published_numbers(owner):
    """No deploy step and no data migration: the singleton is seeded from settings the
    first time anybody looks, so a fresh database advertises exactly 10% and 5%."""
    assert not BusinessDecisions.objects.exists()

    response = owner.get(URL)

    assert response.status_code == 200
    assert response.data == {
        "referrer_commission_percent": "10.00",
        "customer_discount_percent": "5.00",
        "customer_discount_first_order_only": False,
    }


def test_a_manager_can_move_both_numbers(manager):
    response = manager.patch(
        URL,
        {"referrer_commission_percent": "8.50", "customer_discount_percent": "3.00"},
        format="json",
    )

    assert response.status_code == 200
    row = BusinessDecisions.load()
    assert row.referrer_commission_percent == Decimal("8.50")
    assert row.customer_discount_percent == Decimal("3.00")


def test_the_first_order_only_switch_round_trips(owner):
    owner.patch(URL, {"customer_discount_first_order_only": True}, format="json")
    assert BusinessDecisions.load().customer_discount_first_order_only is True


def test_a_second_row_can_never_exist(owner):
    """`save()` forces pk=1. Two rows would mean two answers to "what is the commission
    rate", and the losing one would still be readable by something."""
    owner.patch(URL, {"referrer_commission_percent": "9.00"}, format="json")
    BusinessDecisions(
        referrer_commission_percent=Decimal("1.00"), customer_discount_percent=Decimal("1.00")
    ).save()

    assert BusinessDecisions.objects.count() == 1


# ── the guardrails ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["referrer_commission_percent", "customer_discount_percent"])
@pytest.mark.parametrize("value", ["-1.00", "101.00"])
def test_a_percentage_outside_zero_to_a_hundred_is_refused(owner, field, value):
    """101% commission is not a generous offer, it is a typo that would pay a referrer
    more than the order was worth."""
    response = owner.patch(URL, {field: value}, format="json")

    assert response.status_code == 400
    assert field in response.data


@pytest.mark.parametrize("field", ["referrer_commission_percent", "customer_discount_percent"])
def test_zero_is_allowed_because_it_switches_that_half_off(owner, field):
    """Not a validation hole — a deliberate off switch. Tearing the programme out to
    pause it would leave orphaned commissions and code nobody exercises."""
    assert owner.patch(URL, {field: "0.00"}, format="json").status_code == 200


def test_every_change_is_audited_with_the_old_and_new_value(owner):
    """These are PUBLISHED TERMS. "Who dropped the commission to 4%, and when" has to be
    answerable, and the audit row is the only place it is recorded — the table itself
    keeps no history, because each number is snapshotted onto the commissions and orders
    that used it."""
    owner.patch(URL, {"referrer_commission_percent": "4.00"}, format="json")

    entry = AuditLog.objects.filter(model_label="core.businessdecisions").latest("created_at")
    assert entry.actor_email
    assert "referrer_commission_percent" in entry.changes


def test_a_refused_write_is_not_audited(owner):
    """Audit rows are written only on 2xx. A row for a change that never happened would
    make the log a record of attempts, which is a different and much noisier thing."""
    owner.patch(URL, {"referrer_commission_percent": "500.00"}, format="json")

    assert not AuditLog.objects.filter(model_label="core.businessdecisions").exists()


# ── the storefront is told ───────────────────────────────────────────────────────────


@pytest.fixture
def notify():
    with mock.patch("apps.core.revalidate.notify_storefront") as m:
        yield m


def test_changing_a_rate_flushes_the_storefronts_cached_terms(owner, notify):
    """Pinned because the failure is invisible everywhere else: the API answers 200, the
    row is right, the checkout pays the new rate — and /affiliates goes on advertising the
    old one for up to an hour, because it caches `/referrals/terms/` for that long.

    That drift is the exact thing serving these numbers from the API was meant to prevent,
    so a cache that outlives a change is the same bug with a timer on it."""
    owner.get(URL)  # first touch creates the row
    notify.reset_mock()

    owner.patch(URL, {"referrer_commission_percent": "7.00"}, format="json")

    notify.assert_called_with(["referral-terms"])
