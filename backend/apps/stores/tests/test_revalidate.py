"""The storefront is told the moment the directory changes.

Pinned because the failure is invisible in every other test: the API answers 201, the
row is there, and the public page shows "Stores are coming" for five more minutes.
"""

from unittest import mock

import pytest

from apps.stores.factories import store

pytestmark = pytest.mark.django_db


@pytest.fixture
def notify():
    with mock.patch("apps.stores.revalidate.notify_storefront") as m:
        yield m


def test_creating_a_store_flushes_the_storefront(notify):
    store()
    notify.assert_called_with(["stores"])


def test_hiding_and_archiving_flush_too(notify):
    row = store()
    notify.reset_mock()

    row.is_active = False
    row.save(update_fields=["is_active", "updated_at"])
    assert notify.call_count == 1

    row.delete()
    assert notify.call_count == 2
    notify.assert_called_with(["stores"])
