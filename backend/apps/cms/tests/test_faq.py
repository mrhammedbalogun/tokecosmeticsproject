"""The FAQ: an editable question list, and the boundary its answers cross.

`FaqItem.answer` is injected into a customer's browser with `dangerouslySetInnerHTML`,
exactly as `Page.body` is, and by the same `Content` role — someone deliberately not
trusted with orders or products. The tests that matter here are the ones proving the
storefront can never be handed `answer_source`, and that an unpublished answer is not
public.
"""
import pytest
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.cms.models import FaqCategory, FaqItem

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


@pytest.fixture
def shipping():
    return FaqCategory.objects.create(name="Shipping & delivery", sort=1)


# ── the sanitiser boundary ──────────────────────────────────────────────────────────


def test_an_answer_is_sanitised_on_save_and_the_source_is_kept(shipping):
    item = FaqItem.objects.create(
        category=shipping,
        question="Do you deliver nationwide?",
        answer_source='<p>Yes.<script>alert(1)</script></p><p><a href="/stores">Stores</a></p>',
    )
    assert "<script>" not in item.answer
    assert "alert(1)" not in item.answer
    assert "<p>Yes." in item.answer
    # The submission survives, so a corrected allow-list can be re-applied without
    # asking anyone to retype the answer. Same bargain `Page` strikes.
    assert "<script>" in item.answer_source


def test_the_public_endpoint_never_serves_the_unsanitised_source(client, shipping):
    FaqItem.objects.create(category=shipping, question="Q",
                           answer_source="<p>A</p><script>alert(1)</script>")

    body = APIClient().get("/api/v1/cms/faq/").json()

    assert "answer_source" not in body[0]["items"][0]
    assert "<script>" not in body[0]["items"][0]["answer"]


def test_answer_cannot_be_written_through_the_admin_api(client, shipping):
    """`answer` is derived. If it were writable, the Content role could put arbitrary
    HTML in front of a customer by setting it directly and never touching the source."""
    response = client.post("/api/v1/admin/faq-items/", {
        "category": shipping.id, "question": "Q",
        "answer_source": "<p>clean</p>", "answer": "<script>alert(1)</script>",
    }, format="json")

    assert response.status_code == 201
    assert FaqItem.objects.get().answer == "<p>clean</p>"


# ── what the storefront sees ────────────────────────────────────────────────────────


def test_an_unpublished_answer_is_not_public(shipping):
    FaqItem.objects.create(category=shipping, question="Live", answer_source="<p>a</p>")
    FaqItem.objects.create(category=shipping, question="Draft", answer_source="<p>b</p>",
                           is_published=False)

    body = APIClient().get("/api/v1/cms/faq/").json()

    assert [i["question"] for i in body[0]["items"]] == ["Live"]


def test_an_inactive_category_disappears_with_its_questions(shipping):
    FaqItem.objects.create(category=shipping, question="Q", answer_source="<p>a</p>")
    shipping.is_active = False
    shipping.save()

    assert APIClient().get("/api/v1/cms/faq/").json() == []


def test_categories_and_questions_come_back_in_the_order_the_editor_set(shipping):
    account = FaqCategory.objects.create(name="Account", sort=0)
    FaqItem.objects.create(category=shipping, question="second", answer_source="<p>b</p>", sort=2)
    FaqItem.objects.create(category=shipping, question="first", answer_source="<p>a</p>", sort=1)
    FaqItem.objects.create(category=account, question="only", answer_source="<p>c</p>")

    body = APIClient().get("/api/v1/cms/faq/").json()

    assert [c["slug"] for c in body] == ["account", "shipping-delivery"]
    assert [i["question"] for i in body[1]["items"]] == ["first", "second"]


def test_the_whole_faq_is_one_request_regardless_of_how_many_categories(django_assert_num_queries):
    for n in range(4):
        cat = FaqCategory.objects.create(name=f"Cat {n}", sort=n)
        for q in range(3):
            FaqItem.objects.create(category=cat, question=f"q{q}", answer_source="<p>a</p>")

    # Three, and only one of them is this view's doing: the country middleware resolves
    # the market on every request, then the categories, then ONE prefetch covering every
    # item. The number that matters is that the third does not become one query per
    # category, which is what filtering inside the serializer instead of prefetching
    # would cost — 4 categories would make this 6.
    with django_assert_num_queries(3):
        body = APIClient().get("/api/v1/cms/faq/").json()

    assert sum(len(c["items"]) for c in body) == 12


# ── the admin surface ───────────────────────────────────────────────────────────────


def test_a_category_takes_its_slug_from_its_name(client):
    response = client.post("/api/v1/admin/faq-categories/",
                           {"name": "Returns & refunds"}, format="json")

    assert response.status_code == 201
    assert response.data["slug"] == "returns-refunds"


def test_the_screen_can_tell_an_empty_category_from_a_full_one(client, shipping):
    FaqItem.objects.create(category=shipping, question="Q", answer_source="<p>a</p>")
    FaqCategory.objects.create(name="Account")

    # The admin list is paginated, like every other admin list in this project.
    rows = {r["name"]: r["item_count"]
            for r in client.get("/api/v1/admin/faq-categories/").data["results"]}

    assert rows == {"Shipping & delivery": 1, "Account": 0}


def test_a_question_can_be_deleted_unlike_a_page(client, shipping):
    """A page's slug is a published URL the footer hard-codes, so pages refuse DELETE.
    A question addresses no URL and nothing links to it; a wrong one is disposable."""
    item = FaqItem.objects.create(category=shipping, question="Q", answer_source="<p>a</p>")

    assert client.delete(f"/api/v1/admin/faq-items/{item.id}/").status_code == 204
    assert not FaqItem.objects.exists()


def test_the_faq_is_staff_only(shipping):
    for path in ("/api/v1/admin/faq-categories/", "/api/v1/admin/faq-items/"):
        assert APIClient().get(path).status_code in (401, 403), path


def test_a_category_with_only_drafts_in_it_does_not_appear(shipping):
    """The normal state of a half-written section: the questions are seeded, the answers
    are not written yet. A heading with nothing under it reads as a broken page."""
    FaqItem.objects.create(category=shipping, question="Q", answer_source="<p>a</p>",
                           is_published=False)
    account = FaqCategory.objects.create(name="Account")
    FaqItem.objects.create(category=account, question="Live", answer_source="<p>b</p>")

    body = APIClient().get("/api/v1/cms/faq/").json()

    assert [c["name"] for c in body] == ["Account"]


def test_a_category_returns_the_moment_its_first_answer_is_published(shipping):
    item = FaqItem.objects.create(category=shipping, question="Q", answer_source="<p>a</p>",
                                  is_published=False)
    assert APIClient().get("/api/v1/cms/faq/").json() == []

    item.is_published = True
    item.save()

    assert [c["name"] for c in APIClient().get("/api/v1/cms/faq/").json()] == ["Shipping & delivery"]
