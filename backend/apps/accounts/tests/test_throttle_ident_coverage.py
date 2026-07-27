"""Every throttle in the project must use the XFF-safe get_ident.

Swapping DEFAULT_THROTTLE_CLASSES only covers views that do NOT set throttle_classes.
DRF replaces rather than merges, so any view pinning its own classes silently opts out
of the fix. Search, carts and newsletter each did exactly that and kept the bypass.

This is a guard test rather than a behaviour test: it fails when someone adds a view
using stock throttles, which is the mistake that is easy to make and invisible in review.
"""

import pytest
from django.core.cache import cache
from rest_framework import throttling as drf_throttling

from apps.accounts.throttling import CloudflareIdentMixin


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _all_view_classes():
    """Every DRF APIView reachable from the project's URLconf."""
    from django.urls import get_resolver

    seen = {}

    def walk(resolver, prefix=""):
        for pattern in resolver.url_patterns:
            if hasattr(pattern, "url_patterns"):
                walk(pattern, prefix + str(pattern.pattern))
                continue
            callback = pattern.callback
            cls = getattr(callback, "cls", None) or getattr(callback, "view_class", None)
            if cls is not None:
                seen[f"{cls.__module__}.{cls.__name__}"] = cls

    walk(get_resolver())
    return seen


def test_no_view_uses_a_throttle_with_drfs_xff_get_ident():
    offenders = []
    for name, cls in _all_view_classes().items():
        for throttle_cls in getattr(cls, "throttle_classes", []) or []:
            # Only classes that key on an identity are affected; UserRateThrottle keys on
            # pk when authenticated but still falls back to get_ident when anonymous.
            if not issubclass(throttle_cls, drf_throttling.BaseThrottle):
                continue
            if issubclass(throttle_cls, CloudflareIdentMixin):
                continue
            # A throttle that overrides get_cache_key without touching get_ident is fine
            # only if it never calls get_ident. Be strict: require the mixin.
            if throttle_cls.get_ident is drf_throttling.BaseThrottle.get_ident:
                offenders.append(f"{name} -> {throttle_cls.__module__}.{throttle_cls.__name__}")

    assert not offenders, (
        "These views use a throttle with DRF's X-Forwarded-For-keyed get_ident, so a "
        "rotating XFF prefix mints a fresh bucket per request. Use "
        "apps.accounts.throttling.ScopedRateThrottle (or add CloudflareIdentMixin):\n  "
        + "\n  ".join(sorted(offenders))
    )
