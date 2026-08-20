"""Removing a staff member: `POST /admin/staff/<pk>/remove/`, staff.manage (Owner only).

NOT a row delete, deliberately. A hard `user.delete()` would cascade away any referral
ledger rows, reviews and notification subscriptions the person had, raise PROTECT if
they were also a delivery-partner login, and null the actor on every audit row — the
soft-delete precedent (`AccountDeletionView`) exists for exactly these reasons.
"Remove" here means: strip `is_staff` and every group, set `is_active=False`, revoke
trusted devices and second factors, and blacklist every outstanding refresh token —
the person is off the team and locked out everywhere, and the history keeps its names.
"""
import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.accounts.authentication import mint_admin_token_pair

pytestmark = pytest.mark.django_db


def _staff(django_user_model, email, role):
    user = django_user_model.objects.create_user(email=email, password=None, is_staff=True)
    user.groups.add(Group.objects.get(name=role))
    return user


def _client_for(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_owner_removes_a_manager(django_user_model):
    from apps.accounts.devices import issue_device_token
    from apps.accounts.models import StaffTrustedDevice
    from rest_framework_simplejwt.token_blacklist.models import (
        BlacklistedToken,
        OutstandingToken,
    )

    owner = _staff(django_user_model, "owner@toke.test", "Owner")
    manager = _staff(django_user_model, "manager@toke.test", "Manager")
    # A live session and a trusted browser, both of which must die with the role.
    mint_admin_token_pair(manager)
    issue_device_token(manager)
    assert OutstandingToken.objects.filter(user=manager).exists()

    r = _client_for(owner).post(f"/api/v1/admin/staff/{manager.pk}/remove/")

    assert r.status_code == 200, getattr(r, "data", r)
    manager.refresh_from_db()
    assert manager.is_staff is False
    assert manager.is_active is False
    assert manager.groups.count() == 0
    assert not StaffTrustedDevice.objects.filter(user=manager).exists()
    for token in OutstandingToken.objects.filter(user=manager):
        assert BlacklistedToken.objects.filter(token=token).exists()

    # Off the roster: the list shows staff accounts, and this is no longer one.
    roster = _client_for(owner).get("/api/v1/admin/staff/")
    emails = [row["email"] for row in roster.data["results"]]
    assert "manager@toke.test" not in emails


def test_owner_cannot_remove_their_own_account(django_user_model):
    owner = _staff(django_user_model, "owner@toke.test", "Owner")

    r = _client_for(owner).post(f"/api/v1/admin/staff/{owner.pk}/remove/")

    assert r.status_code == 400
    assert "own" in str(r.data).lower()
    owner.refresh_from_db()
    assert owner.is_staff is True and owner.is_active is True


def test_an_owner_cannot_be_removed(django_user_model):
    """Removing Owners through the API is refused outright — the last-Owner case would
    lock the shop, and a co-Owner coup is a shell-access conversation, not a button."""
    owner = _staff(django_user_model, "owner@toke.test", "Owner")
    other = _staff(django_user_model, "owner2@toke.test", "Owner")

    r = _client_for(owner).post(f"/api/v1/admin/staff/{other.pk}/remove/")

    assert r.status_code == 400
    assert "owner" in str(r.data).lower()
    other.refresh_from_db()
    assert other.is_staff is True and other.is_active is True


def test_a_superuser_cannot_be_removed(django_user_model):
    """`scopes_for_user` short-circuits superusers to every scope regardless of group,
    so a superuser without the Owner group is still an Owner in effect."""
    owner = _staff(django_user_model, "owner@toke.test", "Owner")
    root = django_user_model.objects.create_user(
        email="root@toke.test", password=None, is_staff=True, is_superuser=True
    )

    r = _client_for(owner).post(f"/api/v1/admin/staff/{root.pk}/remove/")

    assert r.status_code == 400
    root.refresh_from_db()
    assert root.is_staff is True and root.is_active is True


def test_unknown_or_non_staff_target_is_404(django_user_model):
    owner = _staff(django_user_model, "owner@toke.test", "Owner")
    customer = django_user_model.objects.create_user(email="cust@toke.test", password=None)

    assert _client_for(owner).post("/api/v1/admin/staff/999999/remove/").status_code == 404
    # A customer account is not a staff member; treating it as one would let this
    # endpoint deactivate shoppers.
    assert (
        _client_for(owner).post(f"/api/v1/admin/staff/{customer.pk}/remove/").status_code
        == 404
    )


def test_manager_cannot_remove_staff(django_user_model):
    """staff.manage is Owner-only; the full role sweep lives in the role matrix."""
    manager = _staff(django_user_model, "manager@toke.test", "Manager")
    support = _staff(django_user_model, "support@toke.test", "Support")

    r = _client_for(manager).post(f"/api/v1/admin/staff/{support.pk}/remove/")

    assert r.status_code == 403
    support.refresh_from_db()
    assert support.is_staff is True
