"""Run the Google reviews header refresh now and print the result.

The beat task does the same nightly and silently; this command exists for the
first manual run after the server key lands (and for poking at a skipped pass).
"""
from django.core.management.base import BaseCommand

from apps.cms.google_reviews import refresh_reviews_meta


class Command(BaseCommand):
    help = "Refresh GoogleReviewsMeta (rating + review count) from Place Details."

    def handle(self, *args, **options):
        result = refresh_reviews_meta()
        if "skipped" in result:
            self.stdout.write(self.style.WARNING(f"skipped: {result['skipped']}"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"rating {result['rating']}, {result['count']} reviews"
            ))
