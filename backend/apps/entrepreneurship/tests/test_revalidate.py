"""The storefront flush, and the one guard on it.

`/entrepreneurial-program` is a PRERENDERED page reading a five-minute tagged fetch, so
without this signal an operator who closes the intake leaves the form collecting
applications for up to five more minutes — which is the one failure the switch exists to
prevent.
"""
from unittest.mock import patch

import pytest

from apps.entrepreneurship.models import ProgramSettings

pytestmark = pytest.mark.django_db


def test_saving_the_switch_flushes_the_programme_tag():
    ProgramSettings.load()  # materialise first, so this save is a real change
    with patch("apps.entrepreneurship.revalidate.notify_storefront") as notify:
        row = ProgramSettings.load()
        row.is_open = False
        row.save()

    notify.assert_called_once_with(["entrepreneurship"])


def test_CREATING_THE_SINGLETON_FLUSHES_NOTHING(db):
    """The trap `apps.core.revalidate.notify_decisions_changed` already documents, and it
    bites identically here.

    `ProgramSettings.load()` materialises the row from its field defaults on first
    touch — which happens on the first config read of any fresh database, INCLUDING
    inside tests, where the database rolls back between them. Firing on create would mean
    a real HTTP POST to the storefront from test setup on any machine where
    `REVALIDATE_SECRET` is set, which on a developer's machine it is. And it would flush
    nothing worth flushing: the defaults are what the storefront already believes.
    """
    ProgramSettings.objects.all().delete()
    with patch("apps.entrepreneurship.revalidate.notify_storefront") as notify:
        ProgramSettings.load()

    notify.assert_not_called()
