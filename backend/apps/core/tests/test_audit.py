"""The BEHAVIOURAL half of the audit guarantee, and the more important half.

`test_audit_guard.py` walks the URLconf and asserts what views DECLARE. This file
drives real HTTP requests and asserts what actually lands in the database — and it
exists in this shape because of a specific, expensive lesson from Plan-16 Task 3b.

That task's guard walker asserted that admin views declared the right authentication
class. Every assertion passed. Meanwhile a preauth token authenticated the ENTIRE
customer surface, because stock `JWTAuthentication` never read the claim those views
were declaring. **A declaration test is satisfiable by a class that ignores the thing it
declares.** From Task 4 onward, every guard walker gets a behavioural twin: not only
"does the view say it is audited", but "did one real request leave one real row".

WHAT IS DRIVEN HERE, deliberately over real HTTP with a real minted admin token rather
than `force_authenticate`:

* every write endpoint on the admin surface, once each, asserting a row appears
  (`WRITE_CASES`, with a completeness test that fails on a new endpoint);
* every read-audited endpoint, asserting a row appears with the query recorded;
* the same-transaction rule, by making the audit insert fail and asserting the mutation
  rolled back;
* the append-only fences, at the model and at the database;
* the deletion/redaction promise, end to end.

`mint_admin_token_pair` rather than `force_authenticate` is not decoration. A forced
request carries no token, so `request.auth` is None and `token_jti` would be empty — the
one field that says WHICH LOGIN acted would be untested, and the day it broke nothing
would notice.
"""
from decimal import Decimal
from urllib.parse import quote

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.authentication import mint_admin_token_pair
from apps.accounts.tests.test_admin_surface_guard import ADMIN_SURFACE
from apps.catalog.factories import ProductFactory, ProductVariantFactory
from apps.core.audit import MAX_CHANGES_BYTES, REDACTED, build_changes
from apps.core.models import AuditLog, AuditLogImmutable, Country
from apps.inventory.factories import StockItemFactory, WarehouseFactory
from apps.orders.factories import OrderFactory
from apps.orders.models import OrderItem
from apps.payments.factories import PaymentFactory

pytestmark = pytest.mark.django_db

# A recognisable, documentation-range address so a failure message says where the IP in
# the row came from. Sent as CF-Connecting-IP because that is the only header
# `throttling.client_ip` trusts — X-Forwarded-For is caller-controlled and ignored.
CLIENT_IP = "203.0.113.9"

postgres_only = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="the append-only trigger is Postgres; on the SQLite fallback save() is the only fence",
)


@pytest.fixture
def owner(django_user_model):
    """A superuser staff account, so one client can drive every scope.

    Superuser rather than four role fixtures because this file is about the AUDIT
    mechanism, not about who may reach what — `test_admin_role_matrix.py` owns that and
    would be duplicated badly by a second, weaker copy here.
    """
    return django_user_model.objects.create_user(
        email="owner@toke.test", is_staff=True, is_superuser=True
    )


@pytest.fixture
def client(owner):
    api = APIClient()
    api.credentials(
        HTTP_AUTHORIZATION=f"Bearer {mint_admin_token_pair(owner)['access']}",
        HTTP_CF_CONNECTING_IP=CLIENT_IP,
    )
    return api


def rows():
    return AuditLog.objects.order_by("pk")


def only_row() -> AuditLog:
    assert rows().count() == 1, list(rows().values("action", "model_label", "object_id"))
    return rows().first()


# ---------------------------------------------------------------------------
# 1. One exercised mutation per admin write endpoint.
# ---------------------------------------------------------------------------
#
# Each case builds the least fixture data that makes its endpoint SUCCEED, because a row
# is only written on 2xx — a case that quietly started 404ing would silently stop
# testing anything, so every case asserts its own status code first.


def _ng():
    return Country.objects.get(code="NG")


def _order(number="TC-900001", status="processing", total="1000.00"):
    ng = _ng()
    warehouse = WarehouseFactory(name="Lagos HQ", location_country="NG", priority=1)
    warehouse.serves_countries.add(ng)
    variant = ProductVariantFactory()
    StockItemFactory(variant=variant, warehouse=warehouse, quantity=8)
    order = OrderFactory(
        number=number, country=ng, currency=ng.currency, reservation_reference=number,
        grand_total=total, status=status, email="customer@example.test",
    )
    OrderItem.objects.create(
        order=order, variant=variant, product_name="X", unit_price="500.00",
        line_total=total, quantity=2, fulfillment_warehouses={"Lagos HQ": 2},
    )
    return order, variant


def _quoted_order(number):
    from apps.shipping.models import ShippingQuote

    ng = _ng()
    order = OrderFactory(
        number=number, country=ng, currency=ng.currency, status="pending_payment",
        reservation_reference=number,
    )
    ShippingQuote.objects.create(order=order, currency=order.currency)
    return order


PRODUCTS_CSV = (
    b"slug,name,brand_slug,status,short_description,category_slugs,sku,variant_name,"
    b"price_ngn,price_gbp,price_usd,price_cad\n"
    b"imported,Imported,,active,,,IMP-1,50ml,5000,,,\n"
)

STOCK_CSV_HEADER = b"sku,warehouse,quantity,reserved,available,low_stock_threshold\n"


def _case_product(client, monkeypatch):
    return client.post(
        "/api/v1/admin/products/",
        {"name": "Glow Serum", "slug": "glow-serum", "status": "active"},
        format="json",
    ), 201


def _case_category(client, monkeypatch):
    return client.post(
        "/api/v1/admin/categories/", {"name": "Skin", "slug": "skin"}, format="json"
    ), 201


def _case_brand(client, monkeypatch):
    return client.post(
        "/api/v1/admin/brands/", {"name": "Toke", "slug": "toke"}, format="json"
    ), 201


def _case_tag(client, monkeypatch):
    return client.post(
        "/api/v1/admin/tags/", {"name": "Vegan", "slug": "vegan"}, format="json"
    ), 201


def _case_collection(client, monkeypatch):
    return client.post(
        "/api/v1/admin/collections/", {"name": "New In", "slug": "new-in"}, format="json"
    ), 201


def _case_variant(client, monkeypatch):
    product = ProductFactory(slug="p-variant")
    return client.post(
        "/api/v1/admin/variants/",
        {"product": product.id, "sku": "SKU-1", "name": "50ml"},
        format="json",
    ), 201


def _case_video(client, monkeypatch):
    product = ProductFactory(slug="p-video")
    return client.post(
        "/api/v1/admin/videos/",
        {"product": product.id, "url": "https://example.test/v.mp4"},
        format="json",
    ), 201


def _case_price(client, monkeypatch):
    variant = ProductVariantFactory()
    ng = _ng()
    return client.post(
        "/api/v1/admin/prices/",
        {"variant": variant.id, "currency": ng.currency_id, "country": ng.code,
         "amount": "5000.00"},
        format="json",
    ), 201


def _case_product_csv_import(client, monkeypatch):
    upload = SimpleUploadedFile("products.csv", PRODUCTS_CSV, content_type="text/csv")
    return client.post(
        "/api/v1/admin/products/import.csv", {"file": upload}, format="multipart"
    ), 200


def _case_stock_create(client, monkeypatch):
    variant = ProductVariantFactory()
    warehouse = WarehouseFactory()
    return client.post(
        "/api/v1/admin/stock/",
        {"variant": variant.id, "warehouse": warehouse.id, "low_stock_threshold": 3},
        format="json",
    ), 201


def _case_stock_adjust(client, monkeypatch):
    item = StockItemFactory(variant=ProductVariantFactory(), warehouse=WarehouseFactory(),
                            quantity=10)
    return client.post(
        f"/api/v1/admin/stock/{item.id}/adjust/",
        {"quantity": 25, "reason": "restock", "note": "delivery #4"},
        format="json",
    ), 200


def _case_stock_csv_import(client, monkeypatch):
    upload = SimpleUploadedFile("stock.csv", STOCK_CSV_HEADER, content_type="text/csv")
    return client.post(
        "/api/v1/admin/stock/import.csv", {"file": upload}, format="multipart"
    ), 200


def _case_order_transition(client, monkeypatch):
    order, _ = _order("TC-900010", status="processing")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/transition/",
        {"to_status": "shipped", "message": "handed to DHL"},
        format="json",
    ), 200


def _case_order_tracking(client, monkeypatch):
    order, _ = _order("TC-900011")
    return client.patch(
        f"/api/v1/admin/orders/{order.number}/tracking/",
        {"tracking_carrier": "DHL", "tracking_number": "123"},
        format="json",
    ), 200


def _case_order_note(client, monkeypatch):
    order, _ = _order("TC-900012")
    return client.patch(
        f"/api/v1/admin/orders/{order.number}/note/",
        {"admin_note": "rang the customer"},
        format="json",
    ), 200


def _case_resolve_review(client, monkeypatch):
    order, _ = _order("TC-900013")
    order.review_reason = "short_payment"
    order.save(update_fields=["review_reason"])
    return client.post(
        f"/api/v1/admin/orders/{order.number}/resolve-review/",
        {"message": "refunded by hand"},
        format="json",
    ), 200


def _case_gateway_refund(client, monkeypatch):
    """The gateway refund path, with a fake gateway registered.

    A fake rather than bank_transfer because `BankTransferGateway` has no `refund()` —
    the live gateway's refund path IS `ManualRefundView` below. Both are exercised.
    """
    from apps.payments.gateways import registry
    from apps.payments.gateways.base import PaymentGateway, RefundResult

    class _Fake(PaymentGateway):
        code = "fakeaudit"
        supported_currencies = {"NGN"}

        def initiate(self, payment, order, return_url=""):  # pragma: no cover
            raise NotImplementedError

        def refund(self, payment, amount, reason=""):
            return RefundResult("succeeded", "rf_audit", {"ok": True})

    monkeypatch.setitem(registry._REGISTRY, "fakeaudit", _Fake())
    order, _ = _order("TC-900014")
    PaymentFactory(order=order, currency=order.currency, gateway="fakeaudit",
                   gateway_reference=order.number, amount="1000.00", status="succeeded")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/refunds/",
        {"amount": "100.00", "reason": "goodwill"},
        format="json",
    ), 201


def _case_manual_refund(client, monkeypatch):
    order, _ = _order("TC-900015")
    PaymentFactory(order=order, currency=order.currency, gateway="bank_transfer",
                   gateway_reference=order.number, amount="1000.00", status="succeeded")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/manual-refund/",
        {"amount": "100.00", "bank_reference": "RF-1", "note": "wired back"},
        format="json",
    ), 201


def _case_confirm_receipt(client, monkeypatch):
    order, _ = _order("TC-900016", status="pending_payment")
    PaymentFactory(order=order, currency=order.currency, gateway="bank_transfer",
                   gateway_reference=order.number, amount="1000.00", status="initiated")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/confirm-payment/",
        {"amount_received": "1000.00", "bank_reference": "BT-1"},
        format="json",
    ), 200


def _case_freight_quote(client, monkeypatch):
    order = _quoted_order("TC-900020")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/freight/quote/",
        {"amount": "40.00", "note": "forwarder quoted 40"},
        format="json",
    ), 200


def _case_freight_waive(client, monkeypatch):
    order = _quoted_order("TC-900021")
    client.post(f"/api/v1/admin/orders/{order.number}/freight/quote/",
                {"amount": "40.00"}, format="json")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/freight/waive/",
        {"note": "goodwill"},
        format="json",
    ), 200


def _case_freight_cancel(client, monkeypatch):
    order = _quoted_order("TC-900022")
    client.post(f"/api/v1/admin/orders/{order.number}/freight/quote/",
                {"amount": "40.00"}, format="json")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/freight/cancel/",
        {"note": "no answer"},
        format="json",
    ), 200


def _case_freight_receipt(client, monkeypatch):
    order = _quoted_order("TC-900023")
    client.post(f"/api/v1/admin/orders/{order.number}/freight/quote/",
                {"amount": "40.00"}, format="json")
    return client.post(
        f"/api/v1/admin/orders/{order.number}/freight/receipt/",
        {"amount_received": "40.00", "bank_reference": "FR-1"},
        format="json",
    ), 200


def _case_staff_invite(client, monkeypatch):
    return client.post(
        "/api/v1/admin/staff/invites/",
        {"email": "newhire@toke.test", "role": "Support"},
        format="json",
    ), 201


def _case_staff_invite_revoke(client, monkeypatch):
    from django.contrib.auth.models import Group

    from apps.accounts.invites import issue_invite

    invite, _token = issue_invite(
        email="revoke-me@toke.test", role=Group.objects.get(name="Support"), invited_by=None
    )
    return client.post(
        f"/api/v1/admin/staff/invites/{invite.pk}/revoke/", {}, format="json"
    ), 200


# view class name -> (case, expected action). One entry per admin view that can WRITE.
# The completeness test below asserts this covers every such view, so a new write
# endpoint fails here rather than joining the surface unexercised.
WRITE_CASES: dict[str, tuple] = {
    "ProductAdminViewSet": (_case_product, "create"),
    "CategoryAdminViewSet": (_case_category, "create"),
    "BrandAdminViewSet": (_case_brand, "create"),
    "TagAdminViewSet": (_case_tag, "create"),
    "CollectionAdminViewSet": (_case_collection, "create"),
    "ProductVariantAdminViewSet": (_case_variant, "create"),
    "ProductVideoAdminViewSet": (_case_video, "create"),
    "PriceAdminViewSet": (_case_price, "create"),
    "ProductCSVImportView": (_case_product_csv_import, "import_csv"),
    "StockItemAdminViewSet": (_case_stock_create, "create"),
    "StockCSVImportView": (_case_stock_csv_import, "import_csv"),
    "AdminOrderTransitionView": (_case_order_transition, "transition"),
    "AdminOrderTrackingView": (_case_order_tracking, "tracking"),
    "AdminOrderNoteView": (_case_order_note, "note"),
    "AdminResolveReviewView": (_case_resolve_review, "resolve_review"),
    "OrderRefundView": (_case_gateway_refund, "refund"),
    "ManualRefundView": (_case_manual_refund, "manual_refund"),
    "ConfirmManualReceiptView": (_case_confirm_receipt, "confirm_bank_transfer"),
    "QuoteFreightView": (_case_freight_quote, "freight_quote"),
    "WaiveFreightView": (_case_freight_waive, "freight_waive"),
    "CancelQuoteView": (_case_freight_cancel, "freight_cancel"),
    "FreightReceiptView": (_case_freight_receipt, "freight_receipt"),
    "StaffInviteListCreateView": (_case_staff_invite, "staff_invite"),
    "StaffInviteRevokeView": (_case_staff_invite_revoke, "staff_invite_revoke"),
}

# Admin views that expose no writing method at all, so there is nothing to exercise.
# Enumerated rather than derived so that a view which LOSES its write route (or gains
# one) shows up as a change here.
READ_ONLY_VIEWS = frozenset(
    {
        "AdminOrderListView",
        "AdminOrderDetailView",
        "AdminRefundsOwedView",
        "StockMovementListView",
        "ProductCSVExportView",
        "StockCSVExportView",
        "AuditLogListView",
        "AdminMeView",
    }
)


def test_the_write_cases_cover_every_admin_write_endpoint():
    """Completeness, so this file is a guarantee rather than a snapshot.

    Without it, a twenty-eighth admin endpoint is simply absent from `WRITE_CASES`, every
    parametrised case still passes, and the suite reports green while one staff action
    leaves no row. That is exactly the failure mode `test_admin_surface_guard.py` was
    rewritten to remove, and the same argument applies here.
    """
    covered = set(WRITE_CASES) | READ_ONLY_VIEWS
    assert covered == set(ADMIN_SURFACE), (
        f"admin views with no audit case and no read-only declaration: "
        f"{sorted(set(ADMIN_SURFACE) - covered)}; "
        f"cases for views that no longer exist: {sorted(covered - set(ADMIN_SURFACE))}"
    )


@pytest.mark.parametrize("view_name", sorted(WRITE_CASES))
def test_every_admin_write_endpoint_writes_a_row(client, owner, monkeypatch, view_name):
    """**The behavioural twin.** One real request per write endpoint, one real row.

    Asserted per case: the request SUCCEEDED (a case that started 404ing would otherwise
    test nothing), exactly one row exists, and it carries the actor, the actor's email
    snapshot, the jti of the token that made the request, and the client IP.

    The jti assertion is the reason this file mints a real token instead of using
    `force_authenticate`. It is the field that distinguishes "the owner did this" from
    "somebody holding the owner's Tuesday session did this", and it is only populated
    when a real credential is presented.
    """
    case, expected_action = WRITE_CASES[view_name]
    AuditLog.objects.all().delete()  # ignore rows a case's own setup made through HTTP

    response, expected_status = case(client, monkeypatch)
    assert response.status_code == expected_status, (
        f"{view_name}: the case must SUCCEED or it proves nothing — "
        f"{response.status_code} {getattr(response, 'data', b'')}"
    )

    row = rows().last()
    assert row is not None, f"{view_name} wrote no audit row"
    assert row.action == expected_action, f"{view_name} recorded action={row.action!r}"
    assert row.actor_id == owner.pk
    assert row.actor_email == owner.email
    assert row.client_ip == CLIENT_IP
    assert row.token_jti, (
        f"{view_name} recorded no token jti — the row says WHO but not WHICH SESSION, "
        f"which is the field that matters on the day a staff token is stolen"
    )


def test_a_stock_adjustment_is_not_recorded_as_an_ordinary_create(client, monkeypatch):
    """A router maps `POST /stock/` and `POST /stock/1/adjust/` onto the same class and
    the same HTTP method. Recording both as "create" would make the single most
    consequential inventory operation — the one that sets the number deciding whether an
    order can be placed at all — indistinguishable from adding a row, which is why the
    mixin prefers the DRF action name over the verb."""
    AuditLog.objects.all().delete()
    response, expected = _case_stock_adjust(client, monkeypatch)

    assert response.status_code == expected, response.data
    row = only_row()
    assert row.action == "adjust"
    assert row.model_label == "inventory.stockitem"
    assert row.changes == {"quantity": 25, "reason": "restock", "note": "delivery #4"}


# ---------------------------------------------------------------------------
# 2. Reads. The revision to design ruling 4, driven.
# ---------------------------------------------------------------------------


def test_listing_orders_records_the_search_term_and_the_result_count(client):
    """The canonical insider event: somebody searched the customer base and got rows.

    A log of writes only cannot see this at all — nothing changed. What makes the row
    useful is the QUERY: "listed every order matching @example.test, 1 result" is the
    sentence, and the count is the scale of what left the building. The rows themselves
    are never stored; a second copy of the customer list inside the audit table would be
    an exfiltration aid rather than a control.
    """
    _order("TC-900030")
    response = client.get("/api/v1/admin/orders/?search=example.test&status=processing")

    assert response.status_code == 200
    row = only_row()
    assert row.action == "list"
    assert row.model_label == "orders.order"
    assert row.changes["query"] == {"search": "example.test", "status": "processing"}
    assert row.changes["result_count"] == 1
    assert "customer@example.test" not in str(row.changes), (
        "the response payload must never be stored — only the query and the count"
    )


def test_opening_one_order_records_which_one(client):
    order, _ = _order("TC-900031")
    assert client.get(f"/api/v1/admin/orders/{order.number}/").status_code == 200

    row = only_row()
    assert (row.action, row.model_label, row.object_id) == ("read", "orders.order", order.number)


def test_exporting_the_catalogue_is_recorded(client):
    """A bulk egress with no personal data in it, audited anyway — the judgement call is
    argued at `ProductCSVExportView`. Whoever can round-trip the whole price list is
    doing something worth one row a month."""
    assert client.get("/api/v1/admin/products/export.csv").status_code == 200
    assert only_row().action == "export_csv"


def test_reading_the_audit_log_is_itself_audited(client):
    """The one place in the codebase where reading a table writes to it.

    Deliberate: `changes` holds other people's data, so by the PII-read rule it qualifies
    on its own merits — and "who has been reading the audit log, and what were they
    filtering for" is the behaviour that precedes somebody deciding which rows to try to
    remove. It does not recurse: one read makes one row.
    """
    _order("TC-900032")
    client.patch("/api/v1/admin/orders/TC-900032/note/", {"admin_note": "x"}, format="json")
    before = rows().count()

    response = client.get("/api/v1/admin/audit/?action=note")

    assert response.status_code == 200
    assert rows().count() == before + 1
    assert rows().last().changes["query"] == {"action": "note"}


def test_a_catalogue_list_is_not_audited(client):
    """The other side of the ruling, asserted so "audit everything" cannot creep in.

    Routine catalogue reads carry no personal data and happen on every admin page load.
    Auditing them would bury the rows that matter under navigation noise, which is the
    failure mode that makes people stop reading a log.
    """
    assert client.get("/api/v1/admin/products/").status_code == 200
    assert rows().count() == 0


# ---------------------------------------------------------------------------
# 3. Same transaction: both or neither.
# ---------------------------------------------------------------------------


def test_a_failing_audit_insert_rolls_the_mutation_back(client, monkeypatch):
    """**The rule that makes this table worth trusting, driven rather than asserted.**

    An admin surface where "the refund went through and nothing recorded it" is possible
    has an audit log that answers a question it cannot be relied on for. So the write is
    inside the mutation's own transaction, and an audit failure takes the mutation with
    it. Fail-closed is the right direction here specifically: this is a staff endpoint,
    used a handful of times a day, where an unrecordable action should simply not happen.

    Simulated by breaking the INSERT itself, which is the failure mode that would really
    occur (a full disk, a broken column, a constraint) — not by patching the mixin, which
    would only prove that the mixin calls what it calls.
    """
    from apps.catalog.models import Category
    from apps.core.models import AuditLog as AuditLogModel

    def boom(self, *args, **kwargs):
        raise DatabaseError("no room at the inn")

    monkeypatch.setattr(AuditLogModel, "save", boom)

    with pytest.raises(DatabaseError):
        client.post("/api/v1/admin/categories/", {"name": "Ghost", "slug": "ghost"},
                    format="json")

    assert not Category.objects.filter(slug="ghost").exists(), (
        "the category was created even though its audit row could not be written — "
        "the mutation and the audit insert are not in the same transaction"
    )


# ---------------------------------------------------------------------------
# 4. `changes`: the allowlist and its two size caps.
# ---------------------------------------------------------------------------


def test_only_allowlisted_keys_reach_the_row(client):
    """The whole answer to "what stops a secret-named field being stored".

    Nothing stops the key ARRIVING — the body is whatever the caller sent, and here it
    carries a plausible-looking `api_secret`. What the allowlist guarantees is that an
    unlisted key is never written, whatever it is called. A scrub-by-name denylist was
    refused for exactly the reason this test is written with an invented field name:
    a denylist only knows the names somebody thought of.
    """
    response = client.post(
        "/api/v1/admin/brands/",
        {"name": "Toke", "slug": "toke", "api_secret": "sk_live_deadbeef",
         "description": "ignored"},
        format="json",
    )

    assert response.status_code == 201
    changes = only_row().changes
    assert changes == {"name": "Toke", "slug": "toke"}
    assert "sk_live_deadbeef" not in str(changes)


def test_an_oversized_body_becomes_a_marker_that_keeps_the_keys():
    """An unbounded JSONField fed from request bodies is a disk-DoS lever: a hostile
    staff session can PATCH a 50MB field as fast as the network allows and every attempt
    is stored forever.

    Truncation keeps the KEYS and marks itself. A silently truncated row reads as a
    complete one, and somebody would later conclude the staff member edited two fields.

    NOTE the input has to be a COLLECTION to reach this path at all. A single huge
    string is absorbed by the per-VALUE cap (see the next test) and never reaches the
    per-row budget — which is the whole point of having both. A list survives per-value
    capping 50 times over, so 50 x ~512 chars clears 8KB and the row-level marker is
    what remains. Getting this wrong once already produced two tests asserting
    contradictory things about the same function.
    """
    changes = build_changes({"name": ["x" * 1_000] * 50, "slug": "y"}, ("name", "slug"))

    assert changes["__truncated__"] is True
    assert changes["__keys__"] == ["name", "slug"]
    assert len(str(changes).encode()) < MAX_CHANGES_BYTES


def test_one_huge_value_does_not_truncate_the_whole_row():
    """The per-value cap, which is why the per-row cap is rarely reached.

    Without it a single 8KB-minus-one value fills the row's entire budget and takes every
    other key down with it into a marker — so the interesting fields (which one was
    touched) lose to the boring one.
    """
    changes = build_changes({"name": "x" * 5_000, "slug": "keep-me"}, ("name", "slug"))

    assert changes["slug"] == "keep-me"
    assert changes["name"].endswith("[truncated]")


def test_a_file_upload_is_recorded_as_text_not_as_bytes(client):
    """Multipart bodies put `UploadedFile` objects in `request.data`, which `JSONField`
    cannot store. Coerced to `str()` — for a file that is its name. Recorded here so the
    CSV import endpoints cannot start 500ing on a JSON-serialisation error inside a
    transaction that would then roll the import back."""
    upload = SimpleUploadedFile("products.csv", PRODUCTS_CSV, content_type="text/csv")
    response = client.post("/api/v1/admin/products/import.csv", {"file": upload},
                           format="multipart")

    assert response.status_code == 200
    assert only_row().action == "import_csv"


# ---------------------------------------------------------------------------
# 5. Append-only: the model fence, the database fence, and the FK.
# ---------------------------------------------------------------------------


def test_an_existing_row_cannot_be_re_saved(client):
    """The application-level fence. Weakest of the three and the one that catches the
    accidental case: a future view that loads a row and calls `.save()`."""
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")
    row = only_row()
    row.action = "something-else"

    with pytest.raises(AuditLogImmutable):
        row.save()


@postgres_only
def test_the_database_refuses_to_rewrite_an_audit_row(client):
    """The fence that actually holds: `QuerySet.update()` never calls `save()`, so
    without the trigger "the model is immutable" would be a claim about one method."""
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")
    pk = only_row().pk

    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=pk).update(action="tampered")


@postgres_only
def test_the_database_refuses_to_delete_an_audit_row(client):
    """Deleting the row is the cleanest way to erase an action; it is refused outright.

    HONEST SCOPE, and it is written on the migration too: a database superuser can
    disable the trigger and root has the data directory. This stops the attacker the log
    is actually pointed at — one operating through the application.
    """
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")

    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.all().delete()


@postgres_only
def test_the_database_permits_exactly_the_redaction_update(client):
    """`changes` is the one column that may be rewritten, and only because a deleted
    customer's values have to be removable. Everything else — including the timestamp —
    is refused, so the property is "the contents of one column can be blanked", not "rows
    can be edited".

    THE FORBIDDEN TIMESTAMP IS A DAY AWAY, NOT `now()`, AND THAT MATTERS. The trigger
    compares `to_jsonb(NEW)` against `to_jsonb(OLD)`, and a `created_at` rewritten to
    `timezone.now()` lands microseconds from the value `auto_now_add` wrote moments
    earlier — close enough to render identically and compare equal, so the trigger
    correctly sees no change and the test flakily "failed" by not raising. It was
    order-dependent only because timing was. Backdating an audit row is the realistic
    attack anyway: making an action look like it happened at a different time is the
    point, and nobody rewrites a timestamp to the value it already has.
    """
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")
    pk = only_row().pk

    AuditLog.objects.filter(pk=pk).update(changes={"name": REDACTED})
    assert AuditLog.objects.get(pk=pk).changes == {"name": REDACTED}

    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=pk).update(
            created_at=timezone.now() - timezone.timedelta(days=1)
        )


def test_deleting_the_actor_keeps_the_row_and_its_email_snapshot(client, owner):
    """SET_NULL plus an immutable snapshot, together.

    CASCADE would make deleting your own staff account the cleanest way to delete
    everything you ever did. PROTECT would make offboarding a support ticket. SET_NULL
    keeps the row, and `actor_email` is why that is not a row saying nobody did it.
    """
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")
    owner.delete()

    row = only_row()
    assert row.actor_id is None
    assert row.actor_email == "owner@toke.test"


# ---------------------------------------------------------------------------
# 6. The mirror line: the database is not the only copy.
# ---------------------------------------------------------------------------


def test_the_security_log_mirrors_the_row_with_keys_but_never_values(client, caplog):
    """Keys and ids only, and that one rule buys three things at once.

    The database stops being the sole copy, so somebody who can blank `changes` (the one
    column the trigger permits) has not erased that the action happened. Customer PII
    stays out of the log stream and therefore out of Sentry breadcrumbs. And because no
    caller-supplied VALUE is ever interpolated, the log-injection lesson from
    `apps/core/log_safety.py` cannot bite here.
    """
    with caplog.at_level("INFO", logger="apps.security"):
        client.post(
            "/api/v1/admin/brands/",
            {"name": "Secretive Brand", "slug": "secretive"},
            format="json",
        )

    mirrored = [r.getMessage() for r in caplog.records if r.getMessage().startswith("audit ")]
    assert len(mirrored) == 1, mirrored
    line = mirrored[0]
    assert "keys=name,slug" in line
    assert "Secretive Brand" not in line, "the mirror must carry keys and ids, never values"
    assert "owner@toke.test" in line  # the actor IS an id, and is the point of the line


# ---------------------------------------------------------------------------
# 7. Retention: the row survives, the values do not.
# ---------------------------------------------------------------------------


def test_deleting_a_customer_hollows_out_their_audit_rows_but_keeps_them(
    client, django_user_model
):
    """**Both promises, held at once.** Create, mutate, delete-and-anonymise, then look.

    Deletion means "your data is gone" and it has to be true of the audit table too, or
    the table is a quiet second copy of everything a customer ever gave us. Audit
    integrity means "staff member X edited customer 123's order at 14:02" stays provable.
    The two are only compatible if the row survives and the VALUES do not — which is
    exactly what is asserted below, in both directions.

    The search row is the interesting one: it has no object id, because a list has no
    object, so it is found by matching the customer's address inside `changes`. Without
    that second pass, deleting a customer would leave their email sitting in the audit
    table as somebody's search term.
    """
    from apps.accounts.tasks import anonymize_deleted_accounts

    customer = django_user_model.objects.create_user(
        email="doomed@example.test", password="Str0ng!pass9"
    )
    order, _ = _order("TC-900040")
    order.user = customer
    order.email = customer.email
    order.save(update_fields=["user", "email"])

    client.get(f"/api/v1/admin/orders/?search={customer.email}")
    client.patch(f"/api/v1/admin/orders/{order.number}/note/",
                 {"admin_note": "spoke to doomed@example.test about delivery"}, format="json")
    assert rows().count() == 2

    customer.is_active = False
    customer.deletion_requested_at = timezone.now() - timezone.timedelta(days=31)
    customer.save(update_fields=["is_active", "deletion_requested_at"])
    assert anonymize_deleted_accounts() == 1

    surviving = list(rows())
    assert len(surviving) == 2, "the rows must survive — deletion is not amnesia"
    assert [r.action for r in surviving] == ["list", "note"]
    assert all(r.actor_email == "owner@toke.test" for r in surviving)
    assert all(r.client_ip == CLIENT_IP for r in surviving)

    # The keys stay: WHICH field was touched is still on the record.
    assert set(surviving[0].changes) == {"query", "result_count"}
    assert set(surviving[1].changes) == {"admin_note"}
    # The values do not.
    for row in surviving:
        assert "doomed@example.test" not in str(row.changes)
        assert all(value == REDACTED for value in row.changes.values())


def test_redaction_is_idempotent(client, django_user_model):
    """The sweep re-runs, and a poison row must not stop it. Re-redacting an already
    hollowed row is a no-op rather than a second UPDATE, which also keeps it from
    tripping the append-only trigger with a pointless write."""
    from apps.core.audit import redact_audit_values

    order, _ = _order("TC-900041")
    client.patch(f"/api/v1/admin/orders/{order.number}/note/",
                 {"admin_note": "hello"}, format="json")

    assert redact_audit_values(model_labels_and_ids=[("orders.order", [order.number])]) == 1
    assert redact_audit_values(model_labels_and_ids=[("orders.order", [order.number])]) == 0
    assert only_row().changes == {"admin_note": REDACTED}


# ---------------------------------------------------------------------------
# 8. The endpoint the mixin cannot cover.
# ---------------------------------------------------------------------------


def test_accepting_a_staff_invite_writes_a_row_even_though_nobody_is_logged_in(settings):
    """**The one action on this surface that had to be audited by hand.**

    `AdminAuditMixin` attributes a row to `request.user`, and this endpoint has none: the
    caller proves an invite token, not a session. Left to the mixin it would write
    nothing — which would make CREATING AN ADMINISTRATOR the single staff action with no
    row, and that is the exact hole the table exists to close.

    The actor recorded is the new staff member. `invited_by` on the invite, plus the
    `staff_invite` row from when it was sent, is what ties it back to the Owner.
    """
    from django.contrib.auth.models import Group

    from apps.accounts.invites import issue_invite

    invite, raw_token = issue_invite(
        email="newhire@toke.test", role=Group.objects.get(name="Support"), invited_by=None
    )

    response = APIClient().post(
        "/api/v1/admin/staff/invites/accept/",
        {"token": raw_token, "password": "Str0ng!pass9"},
        format="json",
    )

    assert response.status_code == 200, response.data
    row = only_row()
    assert row.action == "staff_invite_accept"
    assert row.actor_email == "newhire@toke.test"
    assert row.object_id == str(invite.pk)
    assert row.changes == {"role": "Support", "new_account": True}
    assert "Str0ng!pass9" not in str(row.changes), (
        "the request body carries a password; `changes` here is built from server-side "
        "facts and must never be built from request.data"
    )


def test_the_audit_list_endpoint_filters_by_actor_model_and_date(client, owner):
    """The read side, briefly. `actor` matches the SNAPSHOT column rather than the FK,
    which is the only way to find the rows of a staff member whose account has since been
    deleted — precisely when somebody goes looking."""
    order, _ = _order("TC-900050")
    client.patch(f"/api/v1/admin/orders/{order.number}/note/", {"admin_note": "n"},
                 format="json")
    client.post("/api/v1/admin/tags/", {"name": "T", "slug": "t"}, format="json")

    by_model = client.get("/api/v1/admin/audit/?model=orders.order")
    assert [r["action"] for r in by_model.data["results"]] == ["note"]

    by_actor = client.get("/api/v1/admin/audit/?actor=owner@")
    assert by_actor.data["count"] >= 2

    # quote() the timestamp: `+` is a SPACE in a query string, so an un-encoded
    # `+00:00` offset arrives as `2026-07-30T06:33:52 00:00` and parses as nothing.
    future = quote((timezone.now() + timezone.timedelta(days=1)).isoformat())
    assert client.get(f"/api/v1/admin/audit/?after={future}").data["count"] == 0


def test_an_unparseable_date_filter_is_a_400_not_a_500(client, owner):
    """Found while fixing the test above, and worth its own pin.

    Passing the raw string to `created_at__gte=` lets Django's field validation raise
    from inside the queryset, which DRF does not catch — so a mistyped filter was a 500,
    and now that Sentry is live, an error event. Filter values are user input; a bad one
    is a 400. The un-encoded `+` is the realistic way to send one by accident, so it is
    the case pinned here.
    """
    naive = (timezone.now() + timezone.timedelta(days=1)).isoformat()  # `+` left raw

    response = client.get(f"/api/v1/admin/audit/?after={naive}")

    assert response.status_code == 400
    assert "after" in response.data
    assert client.get("/api/v1/admin/audit/?before=not-a-date").status_code == 400


def test_the_amount_and_the_two_overrides_are_on_the_record_for_a_bank_transfer(client):
    """The single most consequential row this table will hold at launch.

    Bank transfer is the only live gateway, so this endpoint is where goods are released
    against money nobody has verified but the person clicking — and
    `accept_discrepancy` / `allow_duplicate_reference` are the two switches that turn OFF
    the guards against shipping twice against one transfer. If any keys belong in the
    audit table, it is these.
    """
    order, _ = _order("TC-900060", status="pending_payment")
    PaymentFactory(order=order, currency=order.currency, gateway="bank_transfer",
                   gateway_reference=order.number, amount="1000.00", status="initiated")

    response = client.post(
        f"/api/v1/admin/orders/{order.number}/confirm-payment/",
        # `note` is REQUIRED by confirm_manual_receipt whenever accept_discrepancy
        # switches the guard off (services.py: "accepting an amount discrepancy requires
        # a reason"). That makes it the most audit-worthy key on the endpoint: the
        # override says the guard was bypassed, and the note says why.
        {
            "amount_received": "900.00",
            "bank_reference": "BT-9",
            "accept_discrepancy": True,
            "note": "customer underpaid by 100, agreed to write off",
        },
        format="json",
    )

    assert response.status_code == 200, response.data
    row = only_row()
    assert row.action == "confirm_bank_transfer"
    assert row.object_id == order.number
    assert row.changes == {
        "amount_received": "900.00",
        "bank_reference": "BT-9",
        "accept_discrepancy": True,
        "note": "customer underpaid by 100, agreed to write off",
    }
    assert Decimal(row.changes["amount_received"]) == Decimal("900.00")
