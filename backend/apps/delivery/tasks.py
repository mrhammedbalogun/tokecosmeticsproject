from celery import shared_task

from apps.delivery.gig.client import GigError
from apps.delivery.gig.coverage import sync_gig_coverage


@shared_task
def sync_gig_coverage_task() -> dict:
    """Nightly GIG coverage sweep (Plan-32a slice 2). A GIG outage makes tonight's
    sync a no-op, not a crash loop: yesterday's coverage keeps serving checkout,
    which fails toward "offer GIG where we last knew it worked" — the quote call
    itself is the real-time gate."""
    try:
        return sync_gig_coverage()
    except GigError as exc:
        return {"skipped": f"GIG unavailable: {exc}"}
