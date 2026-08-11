"""Refresh the homepage Google-reviews HEADER NUMBERS from Place Details.

Scope is deliberately exactly `GoogleReviewsMeta.rating` + `review_count_text`:
the FEATURED reviews stay curated share-links (design ruling 2026-08-04 on
`GoogleReview` — the API caps at five relevance-picked reviews with no
per-review permalink). `profile_url` also stays admin-owned.

The count is written as the honest verbatim number ("49"), not marketing text —
the nightly task overwrites whatever an admin typed, which is the point of
syncing: the header can never drift from what Google actually shows. The save
fires the cms post_save signal, so the storefront's "cms" tag revalidates
without any extra plumbing.

Failure posture mirrors the GIG syncs: any error keeps yesterday's numbers and
reports {"skipped": ...} — a Google outage must never blank the homepage header.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx
from django.conf import settings

from apps.cms.models import GoogleReviewsMeta

logger = logging.getLogger(__name__)

PLACES_BASE = "https://places.googleapis.com/v1/places"
TIMEOUT = 10.0


def refresh_reviews_meta() -> dict:
    key, place_id = settings.GOOGLE_PLACES_API_KEY, settings.GOOGLE_PLACE_ID
    if not key or not place_id:
        return {"skipped": "GOOGLE_PLACES_API_KEY or GOOGLE_PLACE_ID unset"}

    response = httpx.get(
        f"{PLACES_BASE}/{place_id}",
        params={"fields": "rating,userRatingCount"},
        headers={"X-Goog-Api-Key": key},
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        logger.warning("google reviews meta: HTTP %s %s",
                       response.status_code, response.text[:200])
        return {"skipped": f"HTTP {response.status_code}"}

    data = response.json()
    rating, count = data.get("rating"), data.get("userRatingCount")
    if rating is None or count is None:
        # A listing with no reviews omits both fields; nothing truthful to write.
        logger.warning("google reviews meta: no rating/userRatingCount in %r", data)
        return {"skipped": "no rating in response"}

    meta = GoogleReviewsMeta.objects.first() or GoogleReviewsMeta()
    meta.rating = Decimal(str(rating)).quantize(Decimal("0.1"))
    meta.review_count_text = str(count)
    meta.save()
    return {"rating": str(meta.rating), "count": count}
