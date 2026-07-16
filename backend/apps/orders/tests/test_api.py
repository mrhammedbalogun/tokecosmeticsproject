"""Order APIs. Weighted towards the access-control boundaries: who may read an order,
what a bearer token is allowed to reveal, and who may move one."""
import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.core.models import Country
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.orders.tokens import make_tracking_token

pytestmark = pytest.mark.django_db


def _weasyprint_usable() -> bool:
    """Not `importorskip`: the pip package imports fine, it's the native Pango binding
    that fails — with OSError, which importorskip doesn't catch."""
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


needs_weasyprint = pytest.mark.skipif(
    not _weasyprint_usable(), reason="WeasyPrint needs native Pango (Linux/CI only)"
)


@pytest.fixture
def buyer(django_user_model):
    return django_user_model.objects.create_user(email="buyer@x.com", password="pw12345!")


@pytest.fixture
def staff(django_user_model):
    return django_user_model.objects.create_user(
        email="ops@x.com", password="pw12345!", is_staff=True
    )


def _order(number="TC-900001", user=None, status="processing", **kw):
    ng = Country.objects.get(code="NG")
    order = OrderFactory(number=number, country=ng, currency=ng.currency, status=status,
                         user=user, email=(user.email if user else "guest@x.com"),
                         phone="+2348012345678", grand_total="1000.00", subtotal="1000.00",
                         delivery_option_name="Lagos Island Same-Day",
                         shipping_address={"line1": "14B Awolowo Road", "city": "Ikoyi",
                                           "region": "Lagos", "country": "NG"}, **kw)
    OrderItem.objects.create(order=order, product_name="Shea Butter", sku="SB-200",
                             unit_price="500.00", line_total="1000.00", quantity=2)
    return order


# --- customer ---------------------------------------------------------------


def test_customer_lists_only_their_own_orders(buyer, django_user_model):
    _order("TC-900001", user=buyer)
    other = django_user_model.objects.create_user(email="someone@x.com", password="pw12345!")
    _order("TC-900002", user=other)

    client = APIClient()
    client.force_authenticate(buyer)
    resp = client.get("/api/v1/orders/")

    assert resp.status_code == 200
    assert [o["number"] for o in resp.data["results"]] == ["TC-900001"]


def test_customer_cannot_read_someone_elses_order(buyer, django_user_model):
    other = django_user_model.objects.create_user(email="someone@x.com", password="pw12345!")
    _order("TC-900003", user=other)

    client = APIClient()
    client.force_authenticate(buyer)
    resp = client.get("/api/v1/orders/TC-900003/")

    assert resp.status_code == 404  # not 403 — don't confirm the order exists


def test_anonymous_cannot_read_an_order_without_a_token():
    _order("TC-900004")

    resp = APIClient().get("/api/v1/orders/TC-900004/")

    assert resp.status_code in (401, 403)


def test_owner_sees_the_full_order(buyer):
    _order("TC-900005", user=buyer)

    client = APIClient()
    client.force_authenticate(buyer)
    resp = client.get("/api/v1/orders/TC-900005/")

    assert resp.status_code == 200
    assert resp.data["shipping_address"]["line1"] == "14B Awolowo Road"
    assert resp.data["items"][0]["product_name"] == "Shea Butter"


# --- guest tracking token ---------------------------------------------------


def test_a_valid_token_opens_the_order_without_logging_in():
    _order("TC-900006", tracking_carrier="GIG Logistics", tracking_number="GIG1")

    resp = APIClient().get(f"/api/v1/orders/TC-900006/?token={make_tracking_token('TC-900006')}")

    assert resp.status_code == 200
    assert resp.data["status"] == "processing"
    assert resp.data["tracking_number"] == "GIG1"


def test_the_token_view_redacts_personal_details():
    """The token lives in a forwardable inbox. It answers "where is my parcel?" — it must
    not hand the customer's home address to whoever the mail got passed along to."""
    _order("TC-900007")

    resp = APIClient().get(f"/api/v1/orders/TC-900007/?token={make_tracking_token('TC-900007')}")

    assert resp.status_code == 200
    assert "shipping_address" not in resp.data
    assert "billing_address" not in resp.data
    assert "phone" not in resp.data
    assert "email" not in resp.data


def test_a_token_cannot_open_a_different_order():
    _order("TC-900008")
    _order("TC-900009")

    resp = APIClient().get(f"/api/v1/orders/TC-900009/?token={make_tracking_token('TC-900008')}")

    assert resp.status_code == 404


def test_a_junk_token_is_refused():
    _order("TC-900010")

    resp = APIClient().get("/api/v1/orders/TC-900010/?token=garbage")

    assert resp.status_code in (403, 404)


# --- invoice ----------------------------------------------------------------


def test_invoice_is_owner_only_and_rejects_the_tracking_token():
    """An invoice carries the full name, address and billing details — strictly more than
    the redacted tracking view. A bearer token must not reach it.

    Asserts 401/403 and NOT 404 on purpose: a 404 is also what a missing route returns,
    so accepting it would let this test pass without an endpoint existing at all.
    """
    _order("TC-900011")

    resp = APIClient().get(
        f"/api/v1/orders/TC-900011/invoice.pdf?token={make_tracking_token('TC-900011')}"
    )

    assert resp.status_code in (401, 403), "must be an auth refusal, not a missing route"


@needs_weasyprint
def test_owner_can_download_their_invoice_as_a_pdf(buyer):
    """Skips on Windows: WeasyPrint binds to Pango, which doesn't exist there. Runs on
    Linux/CI — the deploy target — so the happy path is genuinely covered where it ships."""
    _order("TC-900023", user=buyer)

    client = APIClient()
    client.force_authenticate(buyer)
    resp = client.get("/api/v1/orders/TC-900023/invoice.pdf")

    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"


def test_a_customer_cannot_download_someone_elses_invoice(buyer, django_user_model):
    other = django_user_model.objects.create_user(email="someone@x.com", password="pw12345!")
    _order("TC-900024", user=other)

    client = APIClient()
    client.force_authenticate(buyer)
    resp = client.get("/api/v1/orders/TC-900024/invoice.pdf")

    assert resp.status_code == 404  # filtered by owner; never reaches the renderer


# --- admin ------------------------------------------------------------------


def test_admin_can_list_and_filter_by_status(staff):
    _order("TC-900012", status="processing")
    _order("TC-900013", status="delivered")

    client = APIClient()
    client.force_authenticate(staff)
    resp = client.get("/api/v1/admin/orders/?status=delivered")

    assert resp.status_code == 200
    assert [o["number"] for o in resp.data["results"]] == ["TC-900013"]


def test_admin_can_search_by_number_and_email(staff):
    _order("TC-900014", status="processing")

    client = APIClient()
    client.force_authenticate(staff)

    assert len(client.get("/api/v1/admin/orders/?search=900014").data["results"]) == 1
    assert len(client.get("/api/v1/admin/orders/?search=guest@x.com").data["results"]) >= 1


def test_admin_needs_attention_filter_uses_the_review_flag(staff):
    _order("TC-900015", status="processing", review_reason="possible double payment")
    _order("TC-900016", status="processing")

    client = APIClient()
    client.force_authenticate(staff)
    resp = client.get("/api/v1/admin/orders/?needs_attention=true")

    assert [o["number"] for o in resp.data["results"]] == ["TC-900015"]


def test_a_customer_cannot_reach_the_admin_api(buyer):
    client = APIClient()
    client.force_authenticate(buyer)

    assert client.get("/api/v1/admin/orders/").status_code == 403


def test_admin_can_transition_an_order(staff, django_capture_on_commit_callbacks):
    order = _order("TC-900017", status="processing")

    client = APIClient()
    client.force_authenticate(staff)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(f"/api/v1/admin/orders/{order.number}/transition/",
                           {"to_status": "shipped", "message": "collected"}, format="json")

    assert resp.status_code == 200
    order.refresh_from_db()
    assert order.status == "shipped"
    assert order.events.get(type="status:shipped").actor == staff


def test_an_illegal_transition_is_a_400_not_a_500(staff):
    order = _order("TC-900018", status="pending_payment")

    client = APIClient()
    client.force_authenticate(staff)
    resp = client.post(f"/api/v1/admin/orders/{order.number}/transition/",
                       {"to_status": "delivered"}, format="json")

    assert resp.status_code == 400
    assert resp.data["error"] == "illegal_transition"
    order.refresh_from_db()
    assert order.status == "pending_payment"


def test_setting_tracking_then_shipping_puts_the_number_in_the_email(
    staff, settings, django_capture_on_commit_callbacks
):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    order = _order("TC-900019", status="processing")

    client = APIClient()
    client.force_authenticate(staff)
    client.patch(f"/api/v1/admin/orders/{order.number}/tracking/",
                 {"tracking_carrier": "GIG Logistics", "tracking_number": "GIG99"},
                 format="json")
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/api/v1/admin/orders/{order.number}/transition/",
                    {"to_status": "shipped"}, format="json")

    assert "GIG99" in mail.outbox[0].body


def test_admin_can_add_an_internal_note_without_touching_status(staff):
    order = _order("TC-900020", status="processing")

    client = APIClient()
    client.force_authenticate(staff)
    resp = client.patch(f"/api/v1/admin/orders/{order.number}/note/",
                        {"admin_note": "customer called about delivery"}, format="json")

    assert resp.status_code == 200
    order.refresh_from_db()
    assert order.admin_note == "customer called about delivery"
    assert order.status == "processing"
    assert order.events.filter(type="note").exists()


def test_resolving_the_review_flag_is_explicit_and_audited(staff):
    order = _order("TC-900021", status="processing", review_reason="possible double payment")

    client = APIClient()
    client.force_authenticate(staff)
    resp = client.post(f"/api/v1/admin/orders/{order.number}/resolve-review/",
                       {"message": "refunded the second charge"}, format="json")

    assert resp.status_code == 200
    order.refresh_from_db()
    assert order.review_reason == ""
    event = order.events.get(type="review_resolved")
    assert event.actor == staff
    assert event.message == "refunded the second charge"


def test_shipping_a_flagged_order_does_not_clear_the_flag(staff, django_capture_on_commit_callbacks):
    """The whole point of the orthogonal flag: staff shipping a double-payment order must
    not silently erase the reason someone still needs to refund the second charge."""
    order = _order("TC-900022", status="processing", review_reason="possible double payment")

    client = APIClient()
    client.force_authenticate(staff)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/api/v1/admin/orders/{order.number}/transition/",
                    {"to_status": "shipped"}, format="json")

    order.refresh_from_db()
    assert order.status == "shipped"
    assert order.review_reason == "possible double payment"
