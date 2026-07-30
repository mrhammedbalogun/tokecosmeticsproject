"""The staff ROSTER — who currently holds an administrator account.

Task 3 built the invite side: how an administrator comes into existence. This is the
other half of the same question, and the Owner cannot answer it without this endpoint:
*who has one right now, in what role, and is their second factor actually set up?*

WHY IT IS A SEPARATE ENDPOINT FROM THE INVITE LIST. An invite is a capability in
flight; a staff row is a capability that has landed. They have different lifetimes,
different kill switches (revoke vs deactivate) and — the reason that matters here —
different failure modes when they drift. An accepted invite disappears from the useful
part of the invite list forever, so a roster derived from invites would be blind to
exactly the accounts that can log in today, including the Owner's own and any account
created by `createsuperuser` over SSH, which never had an invite at all.

THE PROPERTY WORTH TESTING, and the reason `totp_confirmed` is on the row: Amendment 6's
invariant is that a full admin token requires the whole ceremony. A staff account with
`is_staff=True` and no confirmed TOTP is an account that can pass the password door and
then stop — inert, but also invisible, and "invited three weeks ago, never finished
enrolling" is precisely the row an Owner should be able to see and revoke. Deriving it
from the related row rather than from a duplicated boolean means it cannot go stale.
"""
import pytest
from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PW = "Str0ng!pass9"

STAFF = "/api/v1/admin/staff/"


@pytest.fixture
def owner(django_user_model):
    user = django_user_model.objects.create_user(
        email="owner@toke.test", password=PW, is_staff=True,
        first_name="Toke", last_name="Owner",
    )
    user.groups.add(Group.objects.get(name="Owner"))
    return user


@pytest.fixture
def manager(django_user_model):
    user = django_user_model.objects.create_user(
        email="manager@toke.test", password=PW, is_staff=True, first_name="Mo", last_name="Manager"
    )
    user.groups.add(Group.objects.get(name="Manager"))
    return user


@pytest.fixture
def owner_client(owner):
    client = APIClient()
    client.force_authenticate(owner)
    return client


def rows_by_email(response):
    return {row["email"]: row for row in response.data["results"]}


def test_the_roster_lists_every_staff_account_with_its_role(owner_client, owner, manager):
    response = owner_client.get(STAFF)

    assert response.status_code == 200, response.data
    rows = rows_by_email(response)
    assert set(rows) == {"owner@toke.test", "manager@toke.test"}
    assert rows["owner@toke.test"]["roles"] == ["Owner"]
    assert rows["manager@toke.test"]["roles"] == ["Manager"]
    assert rows["manager@toke.test"]["name"] == "Mo Manager"


def test_customers_are_not_on_the_roster(owner_client, django_user_model, manager):
    """The whole point of the endpoint is the administrator population. A customer
    account appearing here would make the roster a user directory — thousands of rows,
    every one of them personal data, behind a scope granted for a different purpose."""
    django_user_model.objects.create_user(email="shopper@example.com", password=PW)

    rows = rows_by_email(owner_client.get(STAFF))

    assert "shopper@example.com" not in rows


def test_a_staff_account_with_no_confirmed_totp_is_visible_as_such(
    owner_client, manager, django_user_model
):
    """The half-enrolled account: can pass the password door, can reach nothing. It is
    the row an Owner most needs to see, because nothing else surfaces it."""
    from apps.accounts.models import StaffTOTP

    StaffTOTP.objects.create(user=manager, secret_ciphertext="x", confirmed_at=None)
    owner_row_user = django_user_model.objects.get(email="owner@toke.test")
    StaffTOTP.objects.create(
        user=owner_row_user, secret_ciphertext="x", confirmed_at=timezone.now()
    )

    rows = rows_by_email(owner_client.get(STAFF))

    assert rows["manager@toke.test"]["totp_confirmed"] is False
    assert rows["owner@toke.test"]["totp_confirmed"] is True


def test_a_deactivated_staff_account_is_listed_and_flagged(
    owner_client, manager, django_user_model
):
    """Deactivation is the kill switch for a staff member who has left. A roster that
    hid deactivated rows would make it impossible to confirm the switch was thrown."""
    django_user_model.objects.filter(pk=manager.pk).update(is_active=False)

    rows = rows_by_email(owner_client.get(STAFF))

    assert rows["manager@toke.test"]["is_active"] is False


def test_a_superuser_without_a_group_is_still_on_the_roster(owner_client, django_user_model):
    """`createsuperuser` over SSH makes an account with every scope and no group. If the
    roster derived membership from groups alone this account — the most powerful one in
    the system — would be the single account it never showed."""
    django_user_model.objects.create_superuser(email="root@toke.test", password=PW)

    rows = rows_by_email(owner_client.get(STAFF))

    assert rows["root@toke.test"]["roles"] == []
    assert rows["root@toke.test"]["is_superuser"] is True


def test_no_password_material_is_ever_serialised(owner_client, manager):
    """A roster is a list of accounts; a hash on the row would put every administrator's
    password digest behind one GET, offline-crackable at leisure."""
    response = owner_client.get(STAFF)

    # Asserted first, and not merely for a clear failure message: without it this test
    # passes against a 404, which is the shape it had before the endpoint existed. A
    # test that is satisfied by the absence of the thing it guards is not a guard.
    assert response.status_code == 200
    body = response.content.decode()
    assert "password" not in body.lower()
    assert "pbkdf2" not in body.lower()


def test_a_manager_cannot_read_the_roster(manager):
    """`staff.manage` is Owner-only. Knowing who the administrators are, and which of
    them has not finished enrolling a second factor, is a target list."""
    client = APIClient()
    client.force_authenticate(manager)

    assert client.get(STAFF).status_code == 403


def test_anonymous_is_401_not_403():
    assert APIClient().get(STAFF).status_code == 401


def test_completing_the_ceremony_records_last_login(owner_client, owner, settings):
    """The roster's "Last sign-in" column depends on this, and nothing was writing it.

    Found the day the first real Owner signed in to production: `last_login` was still
    NULL immediately afterwards. SimpleJWT only writes it when `UPDATE_LAST_LOGIN` is
    enabled, and even then only from `TokenObtainPairSerializer` — which the staff
    ceremony does not use, because `/auth/admin-token/` mints a preauth token through a
    serializer of its own. So the column would have read "Never" for every administrator
    forever: not merely missing data, but a page actively asserting something false about
    who is dormant.

    TOTP-confirm is the right place to write it and the only one: it is where an admin
    session is actually minted, so it means "last completed the whole ceremony" rather
    than "last typed a password correctly".
    """
    import pyotp
    from django.utils import timezone

    from apps.accounts.authentication import mint_preauth_token
    from apps.accounts.models import StaffTOTP
    from apps.accounts.totp import encrypt_secret, new_secret

    secret = new_secret()
    StaffTOTP.objects.create(
        user=owner, secret_ciphertext=encrypt_secret(secret), confirmed_at=timezone.now()
    )
    assert owner.last_login is None

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {mint_preauth_token(owner)}")
    response = client.post(
        "/api/v1/auth/admin-totp/confirm/", {"code": pyotp.TOTP(secret).now()}, format="json"
    )

    assert response.status_code == 200, response.data
    owner.refresh_from_db()
    assert owner.last_login is not None
