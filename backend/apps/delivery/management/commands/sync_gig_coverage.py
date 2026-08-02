"""Run the GIG coverage sync now and print the unmatched report.

The beat task does the same sync nightly and silently; this command exists for
go-live (first production sweep) and for working the unmatched tail down — each
listed row needs a human to either set `GigLga.region` or conclude GIG serves
somewhere our seed genuinely lacks.
"""
from django.core.management.base import BaseCommand

from apps.delivery.gig.coverage import sync_gig_coverage
from apps.delivery.models import GigLga


class Command(BaseCommand):
    help = "Sync GIG LGA coverage from the API and report unmatched rows."

    def handle(self, *args, **options):
        counts = sync_gig_coverage()
        self.stdout.write(
            "active {active}, home-delivery {home_delivery}, created {created}, "
            "updated {updated}, deactivated {deactivated}, newly matched {newly_matched}, "
            "unmatched {unmatched}".format(**counts)
        )
        unmatched = GigLga.objects.filter(region__isnull=True, is_active=True).order_by(
            "state_name", "lga_name"
        )
        for row in unmatched:
            self.stdout.write(f"  UNMATCHED: {row.state_name} / {row.lga_name}")
