"""Plan-20a: the report endpoints, and the two gates on them.

The gating is the interesting half. Reading an aggregate and taking a file of customer
emails are different acts, and this codebase already ruled on that difference for the
order export — these tests hold the reports to the same line.
"""
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.core.models import Country, Currency
from apps.orders.models import Order

pytestmark = pytest.mark.django_db


def _staff(role: str):
    user = get_user_model().objects.create_user(
        email=f"{role.lower()}-reports@x.com", password="x"
    )
    user.is_staff = True
    user.save()
    user.groups.add(Group.objects.get(name=role))
    return user


def _client(role: str) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=_staff(role))
    return c


def _order(number="TC-9001", total="20000"):
    return Order.objects.create(
        number=number, email="ada@x.com",
        country=Country.objects.get(code="NG"), currency=Currency.objects.get(code="NGN"),
        status="processing", grand_total=Decimal(total),
    )


def test_reports_require_staff():
    assert APIClient().get("/api/v1/admin/reports/revenue/").status_code in (401, 403)


def test_a_manager_can_read_a_report():
    _order()

    response = _client("Manager").get("/api/v1/admin/reports/revenue/")

    assert response.status_code == 200, response.data
    assert response.data["report"] == "revenue"
    assert response.data["rows"][0]["currency"] == "NGN"


def test_SUPPORT_CANNOT_SEE_THE_BOOKS():
    """`reports.view` is Owner and Manager. Support works the order desk."""
    assert _client("Support").get("/api/v1/admin/reports/revenue/").status_code == 403


def test_an_unknown_report_is_a_404_not_an_empty_200():
    assert _client("Manager").get("/api/v1/admin/reports/nope/").status_code == 404


def test_the_end_date_is_INCLUSIVE_for_the_caller():
    """Somebody asking for 1–31 August means the 31st included. A silently short month is
    the off-by-one that makes a person distrust every number on the page."""
    from django.utils import timezone

    today = timezone.localdate()
    order = _order()
    Order.objects.filter(pk=order.pk).update(
        placed_at=timezone.now().replace(hour=23, minute=30)
    )

    response = _client("Manager").get(
        f"/api/v1/admin/reports/revenue/?start={today}&end={today}"
    )

    assert response.data["rows"], "an order placed today was excluded from a today-to-today range"


def test_a_malformed_date_is_refused_rather_than_ignored():
    response = _client("Manager").get("/api/v1/admin/reports/revenue/?start=last-tuesday")

    assert response.status_code == 400


# --- exports ------------------------------------------------------------------------


def test_an_export_streams_csv():
    _order()

    response = _client("Manager").get("/api/v1/admin/reports/revenue/export.csv")

    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    body = b"".join(response.streaming_content).decode()
    assert body.splitlines()[0].startswith("currency")


def test_EXPORTING_A_CUSTOMER_NAMING_REPORT_NEEDS_THE_HIGHER_SCOPE():
    """The precedent is `AdminOrderCSVExportView`: a file with every customer's email is
    bulk egress, which is a different act from reading a total on screen. Manager holds
    both scopes, so the test that proves the rule needs a role that holds only one."""
    from apps.accounts.rbac import scopes_for_role

    # Content holds neither; the interesting case is a scope set with reports.view and
    # NOT orders.manage, which no seeded role has — so assert the rule at its source and
    # then prove the endpoint refuses when the scope is absent.
    assert "orders.manage" in scopes_for_role("Manager")

    from apps.analytics.views import CUSTOMER_NAMING

    assert "top_customers" in CUSTOMER_NAMING


def test_a_customer_naming_export_is_refused_without_orders_manage(monkeypatch):
    _order()
    client = _client("Manager")

    # The Manager legitimately holds orders.manage, so the refusal path is exercised by
    # removing exactly that scope — the rule is "this scope", not "this role".
    import apps.analytics.views as views

    monkeypatch.setattr(
        views, "scopes_for_user", lambda user: frozenset({"reports.view"})
    )

    response = client.get("/api/v1/admin/reports/top_customers/export.csv")

    assert response.status_code == 403
    assert "orders.manage" in response.data["detail"]


def test_the_same_report_is_still_READABLE_on_screen_with_only_reports_view(monkeypatch):
    """The gate is on the export, not on the aggregate: a Manager may see who spends
    most; taking the list away as a file is the escalated act."""
    _order()
    import apps.analytics.views as views

    monkeypatch.setattr(
        views, "scopes_for_user", lambda user: frozenset({"reports.view"})
    )

    assert _client("Manager").get("/api/v1/admin/reports/top_customers/").status_code == 200


def test_an_export_writes_an_audit_row():
    """Read-audited, like the order export: "somebody took the whole revenue history" is a
    sentence worth being able to write."""
    from apps.core.models import AuditLog

    _order()
    AuditLog.objects.all().delete()

    response = _client("Manager").get("/api/v1/admin/reports/revenue/export.csv")
    b"".join(response.streaming_content)

    assert AuditLog.objects.filter(action="export_csv").exists()
