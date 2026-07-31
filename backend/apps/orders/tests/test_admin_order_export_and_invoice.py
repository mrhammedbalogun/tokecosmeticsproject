"""Bulk order egress, and staff invoice reads — Plan-18a Task 2.

Two read routes on the admin surface, both audited, and the reasons differ:

* **The CSV export** is a bulk dump of every customer's email, country and order totals.
  Products and stock already export under the same rule ("a whole-catalogue dump is a bulk
  egress whatever it contains"), and this one contains personal data outright.

* **The invoice** already worked for staff — `OrderInvoiceView` has a staff bypass
  (`orders/views.py:97`) and `CustomerJWTAuthentication` deliberately accepts admin tokens.
  So the admin app could always fetch any customer's invoice. What it could not do is leave
  a trace: that route sits on the CUSTOMER surface, where the audit guard does not reach.
  An invoice carries a home address. This route exists so the read is recorded.
"""
from decimal import Decimal
from itertools import count

import pytest
from rest_framework.test import APIClient

from apps.accounts.tests.factories import grant_role
from apps.core.models import AuditLog, Country
from apps.orders.factories import OrderFactory

pytestmark = pytest.mark.django_db

_numbers = count(300_001)


def make_order(**kw):
    ng = Country.objects.get(code="NG")
    return OrderFactory(
        number=f"TC-{next(_numbers)}", country=ng, currency=ng.currency,
        status=kw.pop("status", "processing"), grand_total=Decimal("2000.00"), **kw,
    )


def client_for(role):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(
        email=f"{role.lower()}@toke.test", password="Str0ng!pass9"
    )
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    c = APIClient()
    c.force_authenticate(user=grant_role(user, role))
    return c


EXPORT = "/api/v1/admin/orders/export.csv"


# --- the CSV export -------------------------------------------------------------------


def test_the_export_returns_a_csv_of_the_orders():
    make_order(email="buyer@example.test")

    r = client_for("Manager").get(EXPORT)

    assert r.status_code == 200, r.content[:200]
    assert r["Content-Type"].startswith("text/csv")
    body = b"".join(r.streaming_content).decode()
    assert "buyer@example.test" in body
    assert "number" in body.splitlines()[0]


def test_the_export_is_attached_rather_than_rendered():
    make_order()

    r = client_for("Manager").get(EXPORT)

    assert "attachment" in r["Content-Disposition"]
    assert "orders.csv" in r["Content-Disposition"]


def test_an_empty_catalogue_of_orders_still_returns_a_header_row():
    """A file with no header reads as a broken export rather than an empty one."""
    r = client_for("Manager").get(EXPORT)

    body = b"".join(r.streaming_content).decode()
    assert body.strip().splitlines()[0].startswith("number")


def test_EXPORTING_EVERY_CUSTOMER_IS_NOT_SUPPORTS_TO_DO():
    """The order LIST is `orders.view` — Support works the desk all day. A bulk dump of
    every customer's email and totals is a different act from reading one order, and it
    follows the products/stock rule: bulk egress sits a scope higher."""
    make_order()

    assert client_for("Support").get(EXPORT).status_code == 403


def test_the_export_is_audited_as_a_read():
    make_order()

    client_for("Manager").get(EXPORT)

    assert AuditLog.objects.filter(action="export_csv", model_label="orders.order").exists()


# --- the invoice ----------------------------------------------------------------------


def invoice_url(order):
    return f"/api/v1/admin/orders/{order.number}/invoice.pdf"


def test_staff_can_fetch_any_order_invoice():
    order = make_order()

    r = client_for("Manager").get(invoice_url(order))

    assert r.status_code == 200, r.content[:200]
    assert r["Content-Type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_the_invoice_is_named_after_the_order():
    order = make_order()

    r = client_for("Manager").get(invoice_url(order))

    assert order.number in r["Content-Disposition"]


def test_READING_AN_INVOICE_IS_AUDITED():
    """The point of this route existing at all. The customer-surface route has a staff
    bypass and works fine — it just leaves no trace, and an invoice carries the customer's
    name, address and billing details."""
    order = make_order()

    client_for("Manager").get(invoice_url(order))

    row = AuditLog.objects.filter(model_label="orders.order", action="read_invoice").first()
    assert row is not None
    assert row.object_id == order.number


def test_support_may_read_an_invoice():
    """Unlike the bulk export. Support ships parcels and an invoice goes in the box —
    one order at a time, and recorded."""
    order = make_order()

    assert client_for("Support").get(invoice_url(order)).status_code == 200


def test_an_unknown_order_is_a_404_not_a_500():
    assert client_for("Manager").get("/api/v1/admin/orders/TC-999999/invoice.pdf").status_code == 404


def test_the_export_path_is_not_swallowed_by_the_order_detail_route():
    """`orders/<str:number>/` sits in the same URLconf. If it matched first, the export
    would 404 as an order number nobody has."""
    make_order()

    assert client_for("Manager").get(EXPORT).status_code == 200
