"""`GET /api/v1/referrals/terms/` — the numbers the /affiliates page advertises.

The point of these tests is not that the endpoint returns 200. It is that what the shop
ADVERTISES and what the shop PAYS come from the same place. Every assertion below either
pins that link, or pins the fact that this public endpoint says nothing about any person.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from rest_framework.test import APIClient

from apps.referrals.tests.factories import customer, ngn

TERMS = "/api/v1/referrals/terms/"


@pytest.mark.django_db
def test_the_terms_are_public():
    """No login. A marketing page is read by people who do not have an account yet —
    that is the entire audience it is written for."""
    assert APIClient().get(TERMS).status_code == 200


@pytest.mark.django_db
def test_it_publishes_the_numbers_the_commission_is_actually_calculated_from():
    body = APIClient().get(TERMS).json()
    assert body["commission_percent"] == "10.00"
    assert body["cookie_days"] == 30
    assert body["hold_days"] == 60


@pytest.mark.django_db
@override_settings(REFERRAL_COMMISSION_PERCENT="12.50", REFERRAL_HOLD_DAYS=45)
def test_changing_the_rate_changes_the_advertisement():
    """THE WHOLE REASON THIS ENDPOINT EXISTS. If this test can be made to pass while the
    storefront still says 10%, the storefront has hardcoded a promise it cannot keep."""
    body = APIClient().get(TERMS).json()
    assert body["commission_percent"] == "12.50"
    assert body["hold_days"] == 45


@pytest.mark.django_db
def test_every_payable_currency_is_listed_with_a_formatted_minimum():
    body = APIClient().get(TERMS).json()
    by_code = {t["currency"]: t for t in body["payout_thresholds"]}
    assert "NGN" in by_code
    assert by_code["NGN"]["amount"] == "20000.00"
    # Formatted by `payments.money.format_money`, so the symbol and the decimal places
    # are the currency row's, not a guess made in JSX.
    assert by_code["NGN"]["amount_display"] == "₦20,000.00"


@pytest.mark.django_db
def test_a_currency_with_no_row_is_skipped_rather_than_guessed():
    """`format_money` needs the Currency row for its symbol and precision. Inventing one
    would publish a minimum in the wrong denomination — worse than omitting it."""
    with override_settings(
        REFERRAL_PAYOUT_THRESHOLDS={"NGN": Decimal("20000.00"), "XYZ": Decimal("5.00")}
    ):
        codes = [t["currency"] for t in APIClient().get(TERMS).json()["payout_thresholds"]]
    assert codes == ["NGN"]


@pytest.mark.django_db
def test_the_elite_tier_is_named_exactly_as_the_dashboard_names_it():
    """The shop published "The ₦200k Club". `serializers.club_name` is the single rule,
    called by both this endpoint and `TierSerializer` — if these ever disagree, a
    customer sees one name in the marketing and another on their own dashboard."""
    from apps.referrals.serializers import club_name

    tier = APIClient().get(TERMS).json()["elite_tiers"][0]
    assert tier["club_name"] == "The ₦200k Club"
    assert tier["club_name"] == club_name(Decimal("200000.00"), ngn())
    assert tier["window_days"] == 90


@pytest.mark.django_db
def test_it_discloses_nothing_about_any_person(django_user_model):
    """An unauthenticated, uncapped endpoint. It is safe only for as long as its body
    stays a page of the contract — no codes, no names, no balances, no counts."""
    from apps.referrals.services import ensure_profile

    user = customer(django_user_model, "amina@x.com", first_name="Amina")
    code = ensure_profile(user).code

    raw = APIClient().get(TERMS).content.decode()

    assert code not in raw
    assert "amina" not in raw.lower()
    for leaked in ("email", "wallet", "balance", "referred_customers", "code"):
        assert leaked not in raw.lower(), leaked


# ── The storefront's offline fallback ────────────────────────────────────────────────

STOREFRONT_TERMS = (
    Path(__file__).resolve().parents[4] / "storefront" / "src" / "lib" / "referral-terms.ts"
)


@pytest.mark.skipif(not STOREFRONT_TERMS.exists(), reason="storefront not checked out")
def test_the_storefront_fallback_still_matches_these_settings():
    """`/affiliates` must never go blank because this API blinked, so the storefront
    keeps a hardcoded copy of the published numbers as a last resort
    (`storefront/src/lib/referral-terms.ts`, `PUBLISHED_TERMS`).

    That copy is the dangerous kind of constant — correct the day it is written, silently
    wrong the day somebody changes the rate here and never opens that file. A wrong number
    there is a wrong ADVERTISEMENT: the shop would be promising a rate it does not pay.

    So this test reads the file. It is deliberately a crude substring check rather than a
    TypeScript parse: it only has to notice that the number moved, and a parser is a
    dependency that would eventually be the reason this stopped running.

    If this fails, change the constant in that file to match — do not delete the assert.
    """
    source = STOREFRONT_TERMS.read_text(encoding="utf-8")

    expected = {
        "commission_percent": f'"{settings.REFERRAL_COMMISSION_PERCENT}"',
        "cookie_days": str(settings.REFERRAL_COOKIE_DAYS),
        "hold_days": str(settings.REFERRAL_HOLD_DAYS),
        "terms_version": f'"{settings.REFERRAL_TERMS_VERSION}"',
    }
    for field, value in expected.items():
        assert f"{field}: {value}," in source, (
            f"storefront PUBLISHED_TERMS.{field} does not match settings "
            f"(expected {value}) — see referral-terms.ts"
        )

    for code, amount in settings.REFERRAL_PAYOUT_THRESHOLDS.items():
        assert f'currency: "{code}", amount: "{amount}"' in source, (
            f"storefront PUBLISHED_TERMS is missing or has a stale minimum for {code}"
        )

    for code, threshold in settings.REFERRAL_ELITE_THRESHOLDS.items():
        assert f'threshold: "{threshold}"' in source, (
            f"storefront PUBLISHED_TERMS has a stale elite threshold for {code}"
        )
