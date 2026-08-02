"""The redirect resolver and its admin surface (Plan-24)."""

import pytest
from django.core.cache import cache

from apps.core.models import Redirect
from apps.core.redirects import bump_version, count_hit, normalise_path, resolve

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# ── normalise_path ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("/our-story/", "/our-story"),
        ("/our-story", "/our-story"),
        ("our-story", "/our-story"),
        ("/Our-Story/", "/our-story"),
        ("/our-story/?utm_source=newsletter", "/our-story"),
        ("/our-story/#team", "/our-story"),
        ("/", "/"),
        ("", "/"),
        ("///", "/"),
        (None, "/"),
    ],
)
def test_ONE_DEFINITION_OF_THE_SAME_URL(raw, expected):
    # Used by BOTH the seeder and the resolver. Two definitions would mean a row written
    # one way that can never match a request made the other way — and every legacy URL
    # ends in a slash while no new one does, so that is not a corner case, it is all of
    # them.
    assert normalise_path(raw) == expected


# ── resolve ──────────────────────────────────────────────────────────────────────────────


def test_a_legacy_url_resolves_with_or_without_its_trailing_slash():
    Redirect.objects.create(old_path="/our-story", new_path="/page/our-story")

    assert resolve("/our-story/").new_path == "/page/our-story"
    assert resolve("/our-story").new_path == "/page/our-story"
    assert resolve("/our-story/?ref=google").new_path == "/page/our-story"


def test_an_unknown_path_is_None_not_an_exception():
    assert resolve("/never-existed") is None


def test_A_MISS_IS_CACHED_TOO(django_assert_num_queries):
    # Without caching the negative, every 404 on the site becomes a database query — and
    # 404 traffic is mostly bots, which is exactly the traffic you least want to pay for.
    assert resolve("/never-existed") is None
    with django_assert_num_queries(0):
        assert resolve("/never-existed") is None


def test_a_hit_is_cached():
    Redirect.objects.create(old_path="/our-story", new_path="/page/our-story")
    assert resolve("/our-story").new_path == "/page/our-story"

    Redirect.objects.filter(old_path="/our-story").update(new_path="/page/changed")
    assert resolve("/our-story").new_path == "/page/our-story"  # still cached

    bump_version()
    assert resolve("/our-story").new_path == "/page/changed"


# ── the hit counter ──────────────────────────────────────────────────────────────────────


def test_hits_are_counted():
    row = Redirect.objects.create(old_path="/our-story", new_path="/page/our-story")
    count_hit(row)
    count_hit(row)
    row.refresh_from_db()
    assert row.hits == 2


def test_A_FAILING_COUNTER_NEVER_BREAKS_THE_REDIRECT(monkeypatch):
    """A redirect that 500s because a counter failed is strictly worse than one that
    under-counts. The bare except in count_hit is deliberate and this is what pins it."""
    row = Redirect.objects.create(old_path="/our-story", new_path="/page/our-story")

    def boom(*args, **kwargs):
        raise RuntimeError("database is having a day")

    monkeypatch.setattr(Redirect.objects, "filter", boom)
    count_hit(row)  # must not raise


# ── the public endpoint ──────────────────────────────────────────────────────────────────


def test_the_public_endpoint_answers_anonymously(client):
    Redirect.objects.create(old_path="/our-story", new_path="/page/our-story")

    response = client.get("/api/v1/meta/redirect/", {"path": "/our-story/"})

    assert response.status_code == 200
    assert response.json() == {
        "old_path": "/our-story",
        "new_path": "/page/our-story",
        "status_code": 301,
    }


def test_the_public_endpoint_404s_an_unknown_path(client):
    assert client.get("/api/v1/meta/redirect/", {"path": "/nope"}).status_code == 404


def test_the_public_endpoint_counts_the_hit(client):
    Redirect.objects.create(old_path="/our-story", new_path="/page/our-story")
    client.get("/api/v1/meta/redirect/", {"path": "/our-story"})
    assert Redirect.objects.get(old_path="/our-story").hits == 1


def test_a_missing_path_param_is_a_404_not_a_500(client):
    assert client.get("/api/v1/meta/redirect/").status_code == 404


# ── the admin serializer's guards ────────────────────────────────────────────────────────


def test_the_serializer_normalises_what_an_admin_types():
    from apps.core.redirects import RedirectAdminSerializer

    s = RedirectAdminSerializer(data={"old_path": "/Old-Story/", "new_path": "/page/x"})
    assert s.is_valid(), s.errors
    assert s.validated_data["old_path"] == "/old-story"


def test_A_SELF_REFERENTIAL_REDIRECT_IS_REFUSED():
    # An infinite loop the browser breaks, not the server — so nothing on our side would
    # ever log it. It has to be refused at write time or not at all.
    from apps.core.redirects import RedirectAdminSerializer

    s = RedirectAdminSerializer(data={"old_path": "/loop", "new_path": "/loop/"})
    assert not s.is_valid()
    assert "point at itself" in str(s.errors)


@pytest.mark.parametrize("code", [200, 307, 404, 500])
def test_only_redirect_status_codes_are_accepted(code):
    from apps.core.redirects import RedirectAdminSerializer

    s = RedirectAdminSerializer(
        data={"old_path": "/a", "new_path": "/b", "status_code": code}
    )
    assert not s.is_valid()


@pytest.mark.parametrize("code", [301, 302, 410])
def test_the_three_useful_codes_are_accepted(code):
    from apps.core.redirects import RedirectAdminSerializer

    s = RedirectAdminSerializer(
        data={"old_path": "/a", "new_path": "/b", "status_code": code}
    )
    assert s.is_valid(), s.errors
