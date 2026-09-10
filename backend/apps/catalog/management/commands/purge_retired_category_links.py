"""Drop product→category assignments that point outside the shop menu.

    manage.py purge_retired_category_links            # prints them, writes nothing
    manage.py purge_retired_category_links --apply    # removes them

WHY THIS EXISTS SEPARATELY FROM `rebuild_shop_menu`
---------------------------------------------------
The rebuild is additive and reversible on purpose: it DEACTIVATES the categories it drops
from the menu and leaves their product rows intact, so a wrong call is undone with a
checkbox. That safety net has a cost, and production showed the size of it — all 69
products were left filed in at least one retired category and some in sixteen. The admin's
product editor cannot offer those as choices (a retired category is invisible to shoppers,
so filing anything there files it nowhere), which leaves every product carrying a tail of
assignments nobody can act on. This is the broom, kept apart from the rebuild because it
is the destructive half and should be run deliberately, once, after the new menu looks
right.

WHAT COUNTS AS OUTSIDE THE MENU
  * a RETIRED category (`is_active=False`) — not in the tree, no page, unreachable
  * a HEADING (`is_assignable=False`) — "Shop By Skin Concerns" gathers its children and
    holds no products; the rebuild clears these, this catches any added by a later flip

REVERSING IT. Every removed pair is printed as `LINK <product-slug> <category-slug>`, so
the run's own output is the backup — capture it. To put them back:

    ssh tokecosmetics '... exec -T web python manage.py shell -c "
    from apps.catalog.models import Product, Category
    for line in open(\\"/tmp/links.txt\\"):
        if not line.startswith(\\"LINK \\"): continue
        _, p, c = line.split()
        Product.objects.get(slug=p).categories.add(Category.objects.get(slug=c))
    "'

The nightly database backup and deploy.sh's pre-deploy dump are the second line of
defence; nothing here touches a product, a price or an order.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category, Product


class Command(BaseCommand):
    help = "Remove product→category links that point at retired categories or headings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Remove them. Without it, nothing is written.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]

        offenders = {
            row.pk: row
            for row in Category.objects.filter(is_active=False)
            | Category.objects.filter(is_assignable=False)
        }
        if not offenders:
            self.stdout.write("Every category is a live, assignable shelf. Nothing to do.")
            return

        # Walked per product rather than as one bulk delete on the through table, because
        # the point of the run is the RECORD: which product loses which category. A bulk
        # `.through.objects.filter(...).delete()` would be one query and no evidence.
        removals: list[tuple[Product, list[Category]]] = []
        for product in (
            Product.objects.filter(categories__pk__in=offenders)
            .distinct()
            .prefetch_related("categories")
        ):
            stale = [c for c in product.categories.all() if c.pk in offenders]
            if stale:
                removals.append((product, stale))

        pairs = 0
        for product, stale in removals:
            for category in sorted(stale, key=lambda c: c.slug):
                kind = "retired" if not category.is_active else "heading"
                self.stdout.write(f"LINK {product.slug} {category.slug}  ({kind})")
                pairs += 1

        # A product left in NO menu category is not broken — it stays in All Products and
        # in search — but it is on no shelf, and that is a thing somebody has to fix by
        # hand. Counted before the write so the number is the same on a dry run.
        orphans = [
            product.slug
            for product, stale in removals
            if not any(
                c.is_active and c.is_assignable
                for c in product.categories.all()
                if c.pk not in offenders
            )
        ]

        if apply:
            with transaction.atomic():
                for product, stale in removals:
                    product.categories.remove(*stale)

        self.stdout.write("")
        self.stdout.write(
            f"{pairs} link(s) across {len(removals)} product(s), "
            f"over {len(offenders)} categor{'y' if len(offenders) == 1 else 'ies'} "
            "outside the menu."
        )
        if orphans:
            self.stdout.write(
                f"{len(orphans)} product(s) end up in no menu category and need filing: "
                + ", ".join(sorted(orphans))
            )
        self.stdout.write("")
        if apply:
            self.stdout.write(self.style.SUCCESS("Applied. Keep the LINK lines above."))
        else:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — nothing was written. Re-run with --apply to commit."
            ))
