"""Instant storefront cache flush on CMS writes (Phase 3, 2026-08-06).

The storefront caches CMS reads for 60 seconds under the "cms" tag and has exposed
`POST /api/revalidate` since Plan-13; this module is the Django caller that was never
built. Signals in `apps.py` call `notify_cms_changed()` on every Banner / section /
review / page write, whatever the write path — admin API, Django admin, or a shell.

FIRE AND FORGET, OFF THE REQUEST THREAD. A CMS save must never fail or slow down
because the storefront was unreachable: the fallback is the pre-existing 60-second
window, which is exactly the behaviour when REVALIDATE_SECRET is unset. Errors are
logged at WARNING and swallowed.
"""

from __future__ import annotations

import logging
import threading

import httpx
from django.conf import settings

log = logging.getLogger(__name__)


def _post(url: str, secret: str, tags: list[str]) -> None:
    try:
        response = httpx.post(
            url,
            json={"tags": tags},
            headers={"x-revalidate-secret": secret},
            timeout=3.0,
        )
        if response.status_code != 200:
            log.warning("Storefront revalidate returned %s for %s", response.status_code, tags)
    except httpx.HTTPError as exc:
        log.warning("Storefront revalidate unreachable (%s); the 60s window covers it", exc)


def notify_storefront(tags: list[str]) -> None:
    """Flush the given storefront cache tags, if a secret is configured."""
    secret = settings.REVALIDATE_SECRET
    if not secret:
        return
    url = f"{settings.STOREFRONT_BASE_URL.rstrip('/')}/api/revalidate"
    # A daemon thread so a hanging storefront cannot hold a worker past its response;
    # the 3s httpx timeout bounds the thread's own life.
    threading.Thread(target=_post, args=(url, secret, tags), daemon=True).start()


def notify_cms_changed(*_args, **_kwargs) -> None:
    """Signal receiver: any CMS content write invalidates the one "cms" tag."""
    notify_storefront(["cms"])
