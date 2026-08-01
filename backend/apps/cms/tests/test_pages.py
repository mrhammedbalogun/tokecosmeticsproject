"""Plan-19a: pages, and the sanitiser that had to ship with them.

The sanitiser tests are the point of this file. `Page.body` is rendered by the storefront
through `dangerouslySetInnerHTML`, and its author is the `Content` role — someone who is
deliberately not trusted with orders or products. If any of these pass a `<script>`
through, that role has script execution on the origin where customers type card details.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.cms.models import Page
from apps.cms.sanitize import clean_html

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


# --- the sanitiser -------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "<a href=\"javascript:alert(1)\">x</a>",
        "<iframe src=\"https://evil.example\"></iframe>",
        "<svg/onload=alert(1)>",
        "<style>body{display:none}</style>",
        "<form action=\"https://evil.example\"><input name=card></form>",
        "<div onclick=\"steal()\">x</div>",
        "<object data=\"evil.swf\"></object>",
        "<a href=\"data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==\">x</a>",
    ],
)
def test_the_sanitiser_removes_every_way_in(payload):
    cleaned = clean_html(payload)

    assert "<script" not in cleaned.lower()
    assert "onerror" not in cleaned.lower()
    assert "onload" not in cleaned.lower()
    assert "onclick" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()
    assert "<iframe" not in cleaned.lower()
    assert "<form" not in cleaned.lower()
    assert "<object" not in cleaned.lower()
    assert "<style" not in cleaned.lower()
    assert "data:text/html" not in cleaned.lower()


def test_it_keeps_the_formatting_policy_prose_actually_uses():
    body = (
        "<h2>Returns</h2><p>Email <a href='mailto:hi@x.com'>us</a> within "
        "<strong>14 days</strong>.</p><ul><li>Unopened</li></ul>"
    )

    cleaned = clean_html(body)

    for fragment in ["<h2>", "<p>", "<strong>", "<ul>", "<li>", "mailto:hi@x.com"]:
        assert fragment in cleaned


def test_a_new_tab_link_cannot_lose_its_noopener():
    """nh3 writes `rel` itself, so an author cannot clear the protection that stops a
    `target=_blank` link reaching back through `window.opener`."""
    cleaned = clean_html('<a href="https://x.com" target="_blank" rel="">x</a>')

    assert "noopener" in cleaned


def test_class_is_stripped_so_copy_cannot_restyle_the_page():
    assert "class=" not in clean_html('<p class="fixed inset-0 z-50">x</p>')


# --- the model -----------------------------------------------------------------------


def test_body_is_derived_from_body_source_on_every_save():
    page = Page.objects.create(title="Terms", slug="terms", body_source="<p>ok</p><script>x</script>")

    assert page.body == "<p>ok</p>"
    assert "<script>" in page.body_source  # the submission is kept, unaltered


def test_re_saving_re_sanitises():
    """So a corrected allow-list can be re-applied without retyping eleven pages."""
    page = Page.objects.create(title="Terms", slug="terms", body_source="<p>a</p>")
    page.body_source = "<p>b</p><script>x</script>"
    page.save()

    assert page.body == "<p>b</p>"


def test_a_slug_is_derived_when_absent():
    assert Page.objects.create(title="Shipping & Delivery").slug == "shipping-delivery"


# --- the public endpoint -------------------------------------------------------------


def test_public_endpoint_serves_a_published_page():
    Page.objects.create(title="Terms", slug="terms", body_source="<p>hi</p>", status=Page.PUBLISHED)

    response = APIClient().get("/api/v1/cms/pages/terms/")

    assert response.status_code == 200
    assert response.data["body"] == "<p>hi</p>"


def test_A_DRAFT_IS_A_404_NOT_A_403():
    """The existence of an unpublished page is not public information, and the
    storefront's job with either answer is identical."""
    Page.objects.create(title="Secret", slug="secret", status=Page.DRAFT)

    assert APIClient().get("/api/v1/cms/pages/secret/").status_code == 404


def test_the_public_page_never_exposes_the_raw_submission():
    """`body_source` holds pre-sanitisation HTML. If it ever leaked, a client could be
    tricked into rendering exactly what the sanitiser exists to remove."""
    Page.objects.create(
        title="Terms", slug="terms", body_source="<script>x</script>", status=Page.PUBLISHED
    )

    response = APIClient().get("/api/v1/cms/pages/terms/")

    assert "body_source" not in response.data


def test_the_list_endpoint_serves_published_pages_for_the_sitemap():
    Page.objects.create(title="A", slug="a", status=Page.PUBLISHED)
    Page.objects.create(title="B", slug="b", status=Page.DRAFT)

    response = APIClient().get("/api/v1/cms/pages/")

    assert [row["slug"] for row in response.data] == ["a"]


# --- the admin surface ---------------------------------------------------------------


def test_admin_requires_staff():
    assert APIClient().get("/api/v1/admin/pages/").status_code in (401, 403)


def test_admin_creates_and_edits(client):
    created = client.post(
        "/api/v1/admin/pages/",
        {"title": "Returns", "slug": "returns", "body_source": "<p>a</p>"},
        format="json",
    )
    assert created.status_code == 201, created.data

    patched = client.patch(
        "/api/v1/admin/pages/returns/", {"status": "published"}, format="json"
    )

    assert patched.status_code == 200
    assert Page.objects.get(slug="returns").is_published


def test_ADMIN_CANNOT_DELETE_A_PAGE(client):
    """A slug is a published URL: the storefront footer hard-codes eleven of them and
    Plan-24's redirects will point at them. Unpublishing is how a page goes away."""
    Page.objects.create(title="Terms", slug="terms")

    response = client.delete("/api/v1/admin/pages/terms/")

    assert response.status_code == 405
    assert Page.objects.filter(slug="terms").exists()


def test_the_admin_cannot_write_body_directly(client):
    """`body` is read-only, so the ONLY route to storefront-rendered HTML is through the
    sanitiser in `save()`."""
    client.post(
        "/api/v1/admin/pages/",
        {"title": "X", "slug": "x", "body_source": "<p>clean</p>", "body": "<script>evil</script>"},
        format="json",
    )

    assert Page.objects.get(slug="x").body == "<p>clean</p>"
