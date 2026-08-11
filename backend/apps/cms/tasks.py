from celery import shared_task

import httpx


@shared_task
def refresh_google_reviews_meta() -> dict:
    """Nightly header-numbers sync (google_reviews.py has the scope and posture).
    Transport errors are a skipped pass, never a crash loop — yesterday's
    numbers keep serving the homepage."""
    from apps.cms.google_reviews import refresh_reviews_meta

    try:
        return refresh_reviews_meta()
    except httpx.HTTPError as exc:
        return {"skipped": f"Google unreachable: {exc}"}
