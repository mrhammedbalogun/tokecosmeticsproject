"""One-off: register the banner artwork that predates the media library.

A COMMAND, not a data migration, deliberately: a data migration runs in CI and every
fresh database, minting MediaAsset rows whose S3 objects do not exist there — a grid of
broken thumbnails baked into migration history. Run this once, on the environment whose
storage actually holds the files:

    python manage.py seed_media_library

Idempotent: a file key already in the library is skipped, so re-running is safe. Each
seeded asset is also bound to the banner(s) showing it, so "where is this used?" is
answered for old artwork exactly as it is for new.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.cms.models import Banner, MediaAsset


class Command(BaseCommand):
    help = "Create MediaAsset rows (and banner bindings) for pre-library banner files."

    @transaction.atomic
    def handle(self, **options):
        by_key: dict[str, MediaAsset] = {a.file.name: a for a in MediaAsset.objects.all()}
        created = bound = 0
        for banner in Banner.objects.all():
            touched = []
            for file_field, asset_field, kind in (
                ("image", "image_asset", MediaAsset.IMAGE),
                ("mobile_image", "mobile_image_asset", MediaAsset.IMAGE),
                ("video", "video_asset", MediaAsset.VIDEO),
            ):
                file = getattr(banner, file_field)
                if not file or getattr(banner, asset_field + "_id"):
                    continue
                asset = by_key.get(file.name)
                if asset is None:
                    asset = MediaAsset.objects.create(
                        file=file.name,
                        kind=kind,
                        original_name=file.name.rsplit("/", 1)[-1][:255],
                        size=self._size_of(file),
                    )
                    by_key[file.name] = asset
                    created += 1
                setattr(banner, asset_field, asset)
                touched.append(asset_field)
            if touched:
                banner.save(update_fields=touched)
                bound += len(touched)
        self.stdout.write(self.style.SUCCESS(
            f"{created} asset(s) created, {bound} banner slot(s) bound."
        ))

    @staticmethod
    def _size_of(file) -> int:
        # Storage HEAD can fail for a key that no longer exists; a seeded size of 0 is
        # honest enough for a display-only field and never worth aborting the run.
        try:
            return file.size
        except Exception:
            return 0
