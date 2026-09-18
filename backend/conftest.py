"""Project-wide pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def _turnstile_off(settings):
    """backend/.env carries a real TURNSTILE_SECRET for manual dev, which would
    switch the auth gate on for the whole suite and 403 every login-shaped test.
    Force the gate off; tests that exercise it opt in per-test.

    TURNSTILE_ADMIN_SECRET is cleared for the same reason: it falls back to
    TURNSTILE_SECRET when empty, so leaving it set would gate /auth/admin-token/
    for the whole suite the day someone puts an admin widget in backend/.env.

    ADMIN_BFF_SECRET is cleared on exactly the same grounds: it will live in
    backend/.env for manual dev against a locally-running admin app, and leaving it set
    would 403 every admin-login-shaped test in the suite the moment it is added there.
    `test_bff_gate.py` opts in per-test."""
    settings.TURNSTILE_SECRET = ""
    settings.TURNSTILE_ADMIN_SECRET = ""
    settings.ADMIN_BFF_SECRET = ""


@pytest.fixture(autouse=True)
def _clear_cache():
    """LocMemCache is process-global; clear it around every test so cached catalog
    responses from one test never leak into another."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _storefront_revalidation_off(settings):
    """backend/.env carries a real REVALIDATE_SECRET for manual dev, and with it set every
    catalogue, CMS, store, redirect and region write in this suite fires a live HTTP POST
    at STOREFRONT_BASE_URL — hundreds of them, from tests that have nothing to do with
    caching. (`apps/core/revalidate.py` documents discovering exactly that.)

    Clearing it makes `notify_storefront` a no-op, which is also the production behaviour
    wherever the secret is unset. Tests that assert on revalidation mock the caller
    directly and are unaffected; `test_revalidate.py` opts back in per-test with
    `override_settings` where it needs a secret present.
    """
    settings.REVALIDATE_SECRET = ""
