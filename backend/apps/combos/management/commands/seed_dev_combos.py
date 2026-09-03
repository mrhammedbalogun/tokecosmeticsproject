"""Three combos over whatever `seed_dev_catalog` left behind.

DEV ONLY, and idempotent: it matches on slug and rewrites, so running it twice does not
leave six bundles. It refuses rather than half-builds when the catalogue is too thin —
a combo of one product is not a combo, and a silently empty one is worse than an error.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.catalog.models import ProductVariant
from apps.combos.models import Combo, ComboItem

RECIPES = [
    {
        "slug": "radiant-glow-combo",
        "name": "Radiant Glow Combo",
        "short_description": "The three we reach for first — cleanse, treat, seal.",
        "description": (
            "<p>Everything a first glow routine needs, in the order you use it. "
            "The cleanser lifts the day off, the serum does the work overnight, and the "
            "butter locks it in.</p>"
        ),
        "discount_percent": Decimal("10"),
        "size": 3,
    },
    {
        "slug": "everyday-essentials-combo",
        "name": "Everyday Essentials Combo",
        "short_description": "The two nobody should run out of.",
        "description": "<p>Restock both at once and stop thinking about it.</p>",
        "discount_percent": Decimal("12.5"),
        "size": 2,
    },
    {
        "slug": "full-shelf-combo",
        "name": "Full Shelf Combo",
        "short_description": "Four products, one box, one price.",
        "description": "<p>For the shelf you are building from scratch.</p>",
        "discount_percent": Decimal("15"),
        "size": 4,
    },
]


class Command(BaseCommand):
    help = "Seed a few combos over the dev catalogue (idempotent)."

    def handle(self, *args, **options):
        # Priced, active variants only — an unpriced component makes the whole combo
        # unpriceable (`components_total`), and a seed that produces invisible combos
        # looks exactly like a broken feature.
        variants = list(
            ProductVariant.objects.filter(
                is_active=True, product__status="active", prices__isnull=False
            )
            .distinct()
            .order_by("id")[:12]
        )
        if len(variants) < 4:
            self.stderr.write(
                "Not enough priced, active variants to build combos from. "
                "Run `manage.py seed_dev_catalog` first."
            )
            return

        cursor = 0
        for recipe in RECIPES:
            picked = [variants[(cursor + i) % len(variants)] for i in range(recipe["size"])]
            cursor += recipe["size"]
            combo, _ = Combo.objects.update_or_create(
                slug=recipe["slug"],
                defaults={
                    "name": recipe["name"],
                    "short_description": recipe["short_description"],
                    "description": recipe["description"],
                    "discount_percent": recipe["discount_percent"],
                    "status": "active",
                    "is_featured": recipe["size"] == 3,
                },
            )
            combo.items.all().delete()
            for position, variant in enumerate(picked):
                ComboItem.objects.create(
                    combo=combo,
                    variant=variant,
                    # A second of one item, so the "×2" path and the per-box quantity
                    # arithmetic are exercised by the seed rather than only by tests.
                    quantity=2 if position == 1 else 1,
                    position=position,
                )
            self.stdout.write(
                f"{combo.name}: {combo.items.count()} items, "
                f"{recipe['discount_percent']}% off"
            )
