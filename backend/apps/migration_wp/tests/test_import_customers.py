"""Plan-22 customer import: the three data-loss rules, and cross-store precedence.

FIXTURES ARE SYNTHETIC. The hashes in `fixtures/customers-*.json` were generated locally
for made-up passwords; no customer material is in this repository, and none ever should be.
"""

import json
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.core.management import CommandError, call_command

from apps.accounts.hashers import PREFIX as WP_HASH_PREFIX
from apps.accounts.models import LegacyIdentity, LegacyStore
from apps.migration_wp.importers.customers import import_customers

pytestmark = pytest.mark.django_db

User = get_user_model()
FIXTURES = Path(__file__).parent / "fixtures"
PASSWORDS = json.loads((FIXTURES / "customers-passwords.json").read_text())


def artifact(store):
    return json.loads((FIXTURES / f"customers-{store}.json").read_text())


def run(store, **kwargs):
    return import_customers(artifact(store), **kwargs)


# ── the happy path ───────────────────────────────────────────────────────────────────────


def test_customers_arrive_and_CAN_ACTUALLY_LOG_IN():
    """The only assertion that matters on cutover day. Not "a row exists" — that the
    password they have been using for years still works."""
    run("legacy_ng")

    ada = User.objects.get(email="ada@example.com")
    assert ada.first_name == "Ada" and ada.last_name == "Okafor"
    assert ada.phone == "+2348012345678"
    assert check_password(PASSWORDS["101"], ada.password)
    assert not check_password("not-her-password", ada.password)


def test_all_three_hash_formats_survive_the_round_trip():
    # The fixtures deliberately mix $wp$, phpass and plain bcrypt, because all three exist
    # across these stores and an importer that mangled one would still look fine on a
    # sample of the other two.
    for store in ("legacy_ng", "legacy_ng_old", "legacy_intl"):
        run(store)
    for identity in LegacyIdentity.objects.select_related("user"):
        expected = PASSWORDS[str(identity.wp_user_id)]
        if identity.user.legacy_source == identity.store:
            assert check_password(expected, identity.user.password), identity


def test_billing_names_are_used_when_the_account_name_is_blank():
    run("legacy_ng")
    ben = User.objects.get(email="ben@example.com")
    assert (ben.first_name, ben.last_name) == ("Ben", "Ibrahim")


def test_a_row_with_no_email_is_skipped_not_invented():
    summary = run("legacy_ng")
    assert summary["skipped_no_usable_email"] == 1
    assert summary["sample_no_email_wp_ids"] == [104]
    assert not LegacyIdentity.objects.filter(wp_user_id=104).exists()


def test_the_summary_carries_no_pii():
    # It is written to logs and pasted into run records. Counts and WordPress ids only.
    blob = json.dumps(run("legacy_ng"))
    for leak in ("ada@example.com", "Ada", "Okafor", "+2348012345678"):
        assert leak not in blob


# ── RULE 1: never overwrite a password a human has chosen ────────────────────────────────


def test_A_PASSWORD_THE_CUSTOMER_CHANGED_IS_NEVER_REVERTED():
    """The cutover scenario the plan called out. Staging imports them in the morning; the
    customer logs in and changes their password; the delta run must not put the old
    WordPress hash back."""
    run("legacy_ng")
    ada = User.objects.get(email="ada@example.com")
    ada.password = make_password("a-password-she-chose-herself")
    ada.save(update_fields=["password"])

    summary = run("legacy_ng")

    ada.refresh_from_db()
    assert check_password("a-password-she-chose-herself", ada.password)
    assert not check_password(PASSWORDS["101"], ada.password)
    assert summary["created"] == 0


def test_a_LOGIN_alone_protects_the_password_because_the_hash_upgrades(settings):
    """The subtler half of rule 1, and the reason the test is "is it still a WordPress
    hash?" rather than "did we create this row?". A customer who merely logs in — never
    touching their password — gets silently rehashed to PBKDF2 by Django's upgrade path.
    From then on the stored hash is not the one WordPress had, and re-importing it would
    be overwriting a hash the customer's own login produced."""
    run("legacy_ng")
    ada = User.objects.get(email="ada@example.com")
    assert ada.password.startswith(WP_HASH_PREFIX)

    # Exactly what a successful login does.
    check_password(PASSWORDS["101"], ada.password, setter=lambda pw: ada.set_password(pw))
    ada.save(update_fields=["password"])
    assert not ada.password.startswith(WP_HASH_PREFIX)

    run("legacy_ng")
    ada.refresh_from_db()
    assert not ada.password.startswith(WP_HASH_PREFIX)
    assert check_password(PASSWORDS["101"], ada.password)


# ── RULE 2: never touch a pre-existing account ───────────────────────────────────────────


def test_A_STAFF_ACCOUNT_IS_NEVER_OVERWRITTEN_BY_A_CUSTOMER_ROW():
    """The worst outcome available in this importer: the owner's own admin account having
    its password replaced by a customer's WordPress hash because the emails matched."""
    staff = User.objects.create_user(email="ada@example.com", password="the-owners-password")
    staff.is_staff = True
    staff.first_name, staff.last_name = "Hammed", "Owner"
    staff.save()

    summary = run("legacy_ng")

    staff.refresh_from_db()
    assert check_password("the-owners-password", staff.password)
    assert staff.is_staff is True
    assert (staff.first_name, staff.last_name) == ("Hammed", "Owner")
    assert staff.legacy_source == ""
    assert summary["attached_to_pre_existing"] == 1
    # ...but the identity IS attached, so Plan-23 can still find their order history.
    assert LegacyIdentity.objects.filter(user=staff, store="legacy_ng", wp_user_id=101).exists()


# ── RULE 3 / idempotency ─────────────────────────────────────────────────────────────────


def test_running_twice_creates_nothing_the_second_time():
    first = run("legacy_ng")
    second = run("legacy_ng")

    assert first["created"] == 3
    assert second["created"] == 0
    assert second["already_imported"] == 3
    assert User.objects.filter(legacy_source="legacy_ng").count() == 3
    assert LegacyIdentity.objects.filter(store="legacy_ng").count() == 3


def test_every_created_user_has_a_toke_id_and_they_are_unique():
    # Rule 3 is about routing creation through the manager. This is what that buys.
    for store in ("legacy_ng", "legacy_ng_old", "legacy_intl"):
        run(store)
    ids = list(User.objects.exclude(legacy_source="").values_list("toke_id", flat=True))
    assert all(i.startswith("TK-") for i in ids)
    assert len(ids) == len(set(ids))


def test_migrated_customers_are_NOT_marked_email_verified():
    # claims.py gates claiming legacy GUEST orders on email_verified_at. A WordPress
    # account proves they once knew a password, not that they control the inbox today.
    run("legacy_ng")
    assert User.objects.filter(legacy_source="legacy_ng", email_verified_at__isnull=False).count() == 0


# ── cross-store precedence ───────────────────────────────────────────────────────────────

ORDERS = [
    ("legacy_ng", "legacy_ng_old", "legacy_intl"),
    ("legacy_intl", "legacy_ng_old", "legacy_ng"),
    ("legacy_ng_old", "legacy_intl", "legacy_ng"),
]


@pytest.mark.parametrize("order", ORDERS, ids=["-".join(o) for o in ORDERS])
def test_NG_WINS_THE_SHARED_CUSTOMER_WHATEVER_ORDER_THE_STORES_IMPORT_IN(order):
    """The 17 cross-store people. If this depended on import order, the staging run and
    the cutover run could hand the same customer two different passwords."""
    for store in order:
        run(store)

    shared = User.objects.get(email="shared@example.com")
    assert shared.legacy_source == "legacy_ng"
    assert shared.last_name == "FromNG"
    assert check_password(PASSWORDS["103"], shared.password)
    assert not check_password(PASSWORDS["202"], shared.password)
    assert not check_password(PASSWORDS["302"], shared.password)


def test_the_shared_customer_keeps_an_identity_on_every_store():
    # All three, because Plan-23 must find their orders on all three.
    for store in ("legacy_ng", "legacy_ng_old", "legacy_intl"):
        run(store)
    shared = User.objects.get(email="shared@example.com")
    assert set(shared.legacy_identities.values_list("store", flat=True)) == {
        "legacy_ng",
        "legacy_ng_old",
        "legacy_intl",
    }


def test_one_user_not_three_for_the_shared_customer():
    for store in ("legacy_ng", "legacy_ng_old", "legacy_intl"):
        run(store)
    assert User.objects.filter(email="shared@example.com").count() == 1


# ── --since ──────────────────────────────────────────────────────────────────────────────


def test_since_skips_customers_registered_before_it():
    summary = run("legacy_ng", since="2025-09-01")
    assert summary["skipped_before_since"] > 0
    assert summary["created"] < 3


def test_since_none_imports_everything():
    assert run("legacy_ng", since=None)["created"] == 3


# ── the management command ───────────────────────────────────────────────────────────────


def test_dry_run_writes_nothing():
    out = StringIO()
    call_command("import_customers", str(FIXTURES / "customers-legacy_ng.json"),
                 "--dry-run", stdout=out)

    assert "DRY RUN" in out.getvalue()
    assert User.objects.filter(legacy_source="legacy_ng").count() == 0
    assert LegacyIdentity.objects.count() == 0


def test_the_command_imports():
    out = StringIO()
    call_command("import_customers", str(FIXTURES / "customers-legacy_ng.json"), stdout=out)
    assert User.objects.filter(legacy_source="legacy_ng").count() == 3
    assert "Imported 3 new customers" in out.getvalue()


def test_AN_ARTIFACT_WITH_AN_UNKNOWN_STORE_IS_REFUSED(tmp_path):
    # LegacyIdentity rows written with a store this codebase does not know would be
    # unmatchable forever — including by the cutover re-run that is supposed to find them.
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": 1, "store": "legacy_typo", "customers": [], "meta": {}}))
    with pytest.raises(CommandError, match="legacy_typo"):
        call_command("import_customers", str(bad))


def test_a_missing_artifact_is_a_clean_error(tmp_path):
    with pytest.raises(CommandError, match="No such artifact"):
        call_command("import_customers", str(tmp_path / "nope.json"))


def test_every_fixture_store_is_a_real_LegacyStore():
    for store in ("legacy_ng", "legacy_ng_old", "legacy_intl"):
        assert artifact(store)["store"] in {s.value for s in LegacyStore}
