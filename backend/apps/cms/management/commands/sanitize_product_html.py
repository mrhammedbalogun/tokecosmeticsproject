"""Run existing product descriptions through the CMS allow-list.

Plan-19a ruling 2 commits to backfilling product descriptions through the sanitiser that
ships with `cms.Page`. This is that backfill, and it DEFAULTS TO A DRY RUN because it
rewrites content on a live catalogue: `--apply` is required to change anything.

Measured against production on 2026-07-31: descriptions use `p, strong, h3, ul, li, h1,
span, h2, b, div, ol, section, br, em`. Two of those are outside the allow-list — `h1`
(once) and `section` (twice). `nh3` drops the tag and KEEPS its text, so nothing is lost;
`<h1>` in a product description is also a genuine defect, since the PDP already has one
and a second confuses both screen readers and search engines.
"""
from django.core.management.base import BaseCommand

from apps.catalog.models import Product
from apps.cms.sanitize import clean_html


class Command(BaseCommand):
    help = "Sanitise product descriptions through the CMS allow-list (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write. Without this the command only reports.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        changed = []
        for product in Product.objects.exclude(description="").only("id", "slug", "description"):
            cleaned = clean_html(product.description)
            if cleaned != product.description:
                changed.append((product, cleaned))

        for product, cleaned in changed:
            before, after = len(product.description), len(cleaned)
            self.stdout.write(f"  {product.slug}: {before} -> {after} chars")

        if not changed:
            self.stdout.write(self.style.SUCCESS("Nothing to change."))
            return

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(changed)} description(s) would change. Re-run with --apply to write."
                )
            )
            return

        for product, cleaned in changed:
            product.description = cleaned
            product.save(update_fields=["description"])
        self.stdout.write(self.style.SUCCESS(f"Sanitised {len(changed)} description(s)."))
