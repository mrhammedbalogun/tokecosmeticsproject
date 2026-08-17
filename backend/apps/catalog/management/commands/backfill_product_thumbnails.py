"""Generate the missing square thumbnails for product images uploaded before the field
existed.

RUN AFTER DEPLOYING the migration that adds `ProductImage.thumbnail`, once. New uploads
generate their own on save; this is only for the back catalogue.

Deliberately a command rather than a data migration. It downloads and re-encodes every
image, which against S3 is minutes of network work — a migration that slow blocks the
deploy's `migrate` step and, if it dies halfway, leaves a release wedged. A command can be
re-run, is idempotent (it skips images that already have one), and its failure costs
nothing: a missing thumbnail falls back to the full-size image, which is the behaviour
that existed before any of this.
"""
from django.core.management.base import BaseCommand

from apps.catalog.models import ProductImage
from apps.catalog.thumbnails import ensure_thumbnail


class Command(BaseCommand):
    help = "Generate thumbnails for product images that have none."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Rebuild thumbnails that already exist (after changing the size or crop).",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Stop after this many images. 0 = no limit.",
        )

    def handle(self, *args, **options):
        queryset = ProductImage.objects.order_by("pk")
        if not options["force"]:
            queryset = queryset.filter(thumbnail="")
        if options["limit"]:
            queryset = queryset[: options["limit"]]

        total = built = failed = 0
        for image in queryset.iterator():
            total += 1
            try:
                if ensure_thumbnail(image.image, image.thumbnail, force=options["force"]):
                    # `update_fields` so this cannot disturb anything else on the row, and
                    # so a concurrent admin edit is not clobbered by a stale in-memory copy.
                    image.save(update_fields=["thumbnail", "updated_at"])
                    built += 1
                    self.stdout.write(f"  {image.pk}: {image.thumbnail.name}")
                else:
                    failed += 1
                    self.stderr.write(f"  {image.pk}: could not build ({image.image.name})")
            except Exception as exc:  # noqa: BLE001
                # One unreadable image must not end the run — the whole point is to get
                # through the back catalogue.
                failed += 1
                self.stderr.write(f"  {image.pk}: {type(exc).__name__}: {exc}")

        self.stdout.write(self.style.SUCCESS(
            f"{total} considered, {built} built, {failed} skipped or failed"
        ))
