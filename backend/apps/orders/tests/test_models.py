import pytest

from apps.orders.numbers import next_order_number

pytestmark = pytest.mark.django_db


def test_order_numbers_increment_from_100001():
    n1 = next_order_number()
    n2 = next_order_number()
    assert n1.startswith("TC-")
    assert int(n2.split("-")[1]) == int(n1.split("-")[1]) + 1
