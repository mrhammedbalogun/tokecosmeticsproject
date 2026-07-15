"""Project-wide pytest fixtures."""
import pytest


@pytest.fixture(autouse=True)
def _clear_cache():
    """LocMemCache is process-global; clear it around every test so cached catalog
    responses from one test never leak into another."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
