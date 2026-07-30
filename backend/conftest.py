"""Project-wide pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def _turnstile_off(settings):
    """backend/.env carries a real TURNSTILE_SECRET for manual dev, which would
    switch the auth gate on for the whole suite and 403 every login-shaped test.
    Force the gate off; tests that exercise it opt in per-test.

    TURNSTILE_ADMIN_SECRET is cleared for the same reason: it falls back to
    TURNSTILE_SECRET when empty, so leaving it set would gate /auth/admin-token/
    for the whole suite the day someone puts an admin widget in backend/.env."""
    settings.TURNSTILE_SECRET = ""
    settings.TURNSTILE_ADMIN_SECRET = ""


@pytest.fixture(autouse=True)
def _clear_cache():
    """LocMemCache is process-global; clear it around every test so cached catalog
    responses from one test never leak into another."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
