"""The recipient table: its constraints, and how it resolves to addresses at send time."""
import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.notifications.models import NotificationRecipient, resolve_recipients

pytestmark = pytest.mark.django_db

User = get_user_model()


def staff(email, **kw):
    return User.objects.create_user(email=email, password="x", is_staff=True, **kw)


def test_two_staff_rows_on_one_event_are_allowed():
    """THE REGRESSION THIS TABLE WAS NEARLY SHIPPED WITH. A plain `unique_together
    (event, email)` collides here: staff rows all store `email=""`, and the empty string
    is a value rather than a NULL, so the SECOND colleague added to an event would raise
    IntegrityError. It survives any happy-path test with one recipient and appears the
    day the shop adds somebody."""
    a, b = staff("a@x.com"), staff("b@x.com")
    NotificationRecipient.objects.create(event="order.paid", user=a)
    NotificationRecipient.objects.create(event="order.paid", user=b)
    assert NotificationRecipient.objects.filter(event="order.paid").count() == 2


def test_the_same_staff_member_cannot_be_added_twice():
    a = staff("a@x.com")
    NotificationRecipient.objects.create(event="order.paid", user=a)
    with pytest.raises(IntegrityError), transaction.atomic():
        NotificationRecipient.objects.create(event="order.paid", user=a)


def test_the_same_address_cannot_be_added_twice():
    NotificationRecipient.objects.create(event="order.paid", email="p@x.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        NotificationRecipient.objects.create(event="order.paid", email="p@x.com")


def test_case_differing_addresses_collide():
    """`save()` lowercases, so the constraint can see the collision. Without that these
    are two rows and one inbox gets every alert twice."""
    NotificationRecipient.objects.create(event="order.paid", email="P@X.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        NotificationRecipient.objects.create(event="order.paid", email="p@x.com")


def test_a_row_with_neither_target_is_refused():
    """The failure this table exists to end: a subscription that mails nobody."""
    with pytest.raises(IntegrityError), transaction.atomic():
        NotificationRecipient.objects.create(event="order.paid")


def test_a_row_with_both_targets_is_refused():
    a = staff("a@x.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        NotificationRecipient.objects.create(event="order.paid", user=a, email="p@x.com")


def test_resolution_follows_the_account_not_a_copy():
    a = staff("a@x.com")
    NotificationRecipient.objects.create(event="order.paid", user=a)
    a.email = "moved@x.com"
    a.save(update_fields=["email"])
    assert resolve_recipients("order.paid") == ["moved@x.com"]


def test_a_deactivated_staff_member_stops_receiving_immediately():
    """The whole argument for the ForeignKey. Deactivation in this codebase is a flag
    flip, not a delete, so nothing cascades — resolution has to re-check."""
    a = staff("a@x.com")
    NotificationRecipient.objects.create(event="order.paid", user=a)
    a.is_active = False
    a.save(update_fields=["is_active"])
    assert resolve_recipients("order.paid") == []


def test_a_demoted_staff_member_stops_receiving_immediately():
    a = staff("a@x.com")
    NotificationRecipient.objects.create(event="order.paid", user=a)
    a.is_staff = False
    a.save(update_fields=["is_staff"])
    assert resolve_recipients("order.paid") == []


def test_one_person_listed_twice_is_emailed_once():
    """A manager who is both a staff row and a standalone row. Two identical mails per
    order reads as a broken system."""
    a = staff("sales@x.com")
    NotificationRecipient.objects.create(event="order.paid", user=a)
    NotificationRecipient.objects.create(event="order.paid", email="SALES@x.com")
    assert resolve_recipients("order.paid") == ["sales@x.com"]


def test_an_unregistered_event_resolves_to_nobody_without_raising():
    NotificationRecipient.objects.create(event="gone.away", email="p@x.com")
    assert resolve_recipients("gone.away") == []


def test_events_do_not_leak_into_each_other():
    NotificationRecipient.objects.create(event="order.paid", email="a@x.com")
    NotificationRecipient.objects.create(event="inventory.low_stock", email="b@x.com")
    assert resolve_recipients("order.paid") == ["a@x.com"]
    assert resolve_recipients("inventory.low_stock") == ["b@x.com"]
