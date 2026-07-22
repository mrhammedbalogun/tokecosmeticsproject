"""Seed a realistic DEV catalog so the storefront (Plan-13) can be designed and
verified against real API responses. Seed data ONLY — no schema changes. Idempotent:
every object is get_or_create'd by slug/sku; re-running never duplicates.

DEV-ONLY: refuses to run when DEBUG is False (production backstop).
"""
import io
import random
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.catalog.models import (
    Brand, Category, Collection, Product, ProductImage, ProductVariant, Tag,
)
from apps.core.models import Country, Currency
from apps.inventory.models import StockItem, Warehouse
from apps.pricing.models import Price
from apps.reviews.models import Review
from apps.reviews.services import recompute_product_rating

# --- palette for generated placeholder "product shots" (brand tones) ---
PALETTES = [
    ((251, 249, 245), (28, 122, 62)),    # cream -> forest green
    ((241, 234, 224), (201, 162, 39)),   # beige -> soft gold
    ((251, 249, 245), (140, 198, 63)),   # cream -> leaf
    ((241, 234, 224), (26, 26, 26)),     # beige -> ink
    ((251, 249, 245), (107, 104, 98)),   # cream -> warm grey
]

CATEGORIES = [  # (name, slug, children)
    ("Face", "face", ["Cleansers", "Serums", "Moisturisers"]),
    ("Body", "body", ["Body Butters", "Body Washes"]),
    ("Hair", "hair", []),
    ("Kids & Babies", "kids-babies", []),
    ("Men", "men", []),
]

TAGS = [  # skin concerns (homepage "shop by concern" grid + PLP ?tag= filter)
    ("Acne", "acne"), ("Hyperpigmentation", "hyperpigmentation"),
    ("Dry Skin", "dry-skin"), ("Oily Skin", "oily-skin"),
    ("Sensitive Skin", "sensitive-skin"), ("Eczema", "eczema"),
    ("Dark Spots", "dark-spots"), ("Uneven Tone", "uneven-tone"),
]

BRANDS = [
    ("Toke Naturals", "toke-naturals"), ("Shea Republic", "shea-republic"),
    ("Ajali Botanics", "ajali-botanics"), ("Lumiere Lagos", "lumiere-lagos"),
]

# (name, slug, brand, category, tags, sizes, (NGN, GBP, USD, CAD) base, on_sale, featured)
PRODUCTS = [
    ("Radiance Glow Serum", "radiance-glow-serum", "toke-naturals", "serums",
     ["hyperpigmentation", "dark-spots"], ["30ml", "50ml"],
     ("18500", "32.00", "39.00", "52.00"), True, True),
    ("Shea Whip Body Butter", "shea-whip-body-butter", "shea-republic", "body-butters",
     ["dry-skin"], ["200ml", "400ml"], ("9500", "16.50", "21.00", "27.00"), False, True),
    ("Gentle Oat Cleanser", "gentle-oat-cleanser", "toke-naturals", "cleansers",
     ["sensitive-skin"], ["150ml"], ("7200", "12.00", "15.00", "19.50"), False, True),
    ("Clear Skin Turmeric Bar", "clear-skin-turmeric-bar", "ajali-botanics", "cleansers",
     ["acne", "uneven-tone"], ["120g"], ("4500", "8.00", "10.00", "13.00"), True, False),
    ("Midnight Repair Cream", "midnight-repair-cream", "lumiere-lagos", "moisturisers",
     ["dry-skin", "uneven-tone"], ["50ml"], ("21500", "36.00", "44.00", "58.00"), False, True),
    ("Baby Soft Oil", "baby-soft-oil", "shea-republic", "kids-babies",
     ["sensitive-skin", "eczema"], ["100ml", "250ml"],
     ("6800", "11.50", "14.00", "18.00"), False, False),
    ("Vitamin C Brightening Toner", "vitamin-c-brightening-toner", "toke-naturals", "face",
     ["dark-spots", "hyperpigmentation"], ["200ml"],
     ("11200", "19.00", "24.00", "31.00"), True, True),
    ("Black Soap Deep Cleanse", "black-soap-deep-cleanse", "ajali-botanics", "body-washes",
     ["acne", "oily-skin"], ["250ml", "500ml"], ("5900", "10.00", "12.50", "16.00"), False, False),
    ("Cocoa Silk Hair Butter", "cocoa-silk-hair-butter", "shea-republic", "hair",
     [], ["150ml"], ("8400", "14.00", "17.50", "22.50"), False, False),
    ("Even Tone Night Mask", "even-tone-night-mask", "lumiere-lagos", "face",
     ["uneven-tone", "hyperpigmentation"], ["75ml"], ("16800", "28.00", "35.00", "46.00"), True, False),
    ("Calm Balm for Eczema", "calm-balm-eczema", "toke-naturals", "body",
     ["eczema", "sensitive-skin"], ["60ml"], ("9900", "17.00", "21.00", "27.50"), False, False),
    ("Papaya Enzyme Scrub", "papaya-enzyme-scrub", "ajali-botanics", "face",
     ["uneven-tone"], ["100ml"], ("7600", "13.00", "16.00", "21.00"), False, False),
    ("Hydra Dew Moisturiser", "hydra-dew-moisturiser", "toke-naturals", "moisturisers",
     ["dry-skin"], ["50ml", "100ml"], ("12800", "22.00", "27.00", "35.00"), False, True),
    ("Men's Beard + Face Oil", "mens-beard-face-oil", "lumiere-lagos", "men",
     ["dry-skin"], ["30ml"], ("10500", "18.00", "22.50", "29.00"), False, False),
    ("Charcoal Detox Wash", "charcoal-detox-wash", "ajali-botanics", "men",
     ["oily-skin", "acne"], ["200ml"], ("6900", "11.50", "14.50", "18.50"), True, False),
    ("Kids Curl Cream", "kids-curl-cream", "shea-republic", "kids-babies",
     [], ["150ml"], ("5500", "9.50", "12.00", "15.50"), False, False),
    ("Rosehip Recovery Oil", "rosehip-recovery-oil", "lumiere-lagos", "serums",
     ["dark-spots", "dry-skin"], ["30ml"], ("14500", "24.50", "30.00", "39.00"), False, False),
    ("Aloe Rescue Gel", "aloe-rescue-gel", "toke-naturals", "body",
     ["sensitive-skin"], ["120ml"], ("4900", "8.50", "10.50", "13.50"), False, False),
    ("Silk Press Shampoo", "silk-press-shampoo", "shea-republic", "hair",
     [], ["300ml"], ("7800", "13.50", "16.50", "21.50"), False, False),
    ("Glow Duo Face Kit", "glow-duo-face-kit", "toke-naturals", "face",
     ["hyperpigmentation"], ["Kit"], ("26500", "45.00", "55.00", "70.00"), True, True),
    ("Tea Tree Spot Serum", "tea-tree-spot-serum", "ajali-botanics", "serums",
     ["acne"], ["15ml"], ("8900", "15.00", "19.00", "24.50"), False, False),
    ("Mango Lip + Cheek Balm", "mango-lip-cheek-balm", "shea-republic", "face",
     [], ["20g"], ("4600", "8.00", "10.00", "12.80"), False, False),
    ("Overnight Hand Repair", "overnight-hand-repair", "lumiere-lagos", "body",
     ["dry-skin"], ["75ml"], ("7100", "12.00", "15.00", "19.00"), False, False),
    ("Balance Facial Mist", "balance-facial-mist", "toke-naturals", "face",
     ["oily-skin", "sensitive-skin"], ["100ml"], ("6300", "10.50", "13.00", "17.00"), False, False),
]

REVIEW_BODIES = [
    (5, "Absolute holy grail", "My hyperpigmentation faded within weeks. Texture is silk."),
    (5, "Worth every naira", "Smells divine and a little goes a very long way."),
    (4, "Really good", "Gentle on my sensitive skin, no purging. Wish the jar were bigger."),
    (5, "Family favourite", "I use it on the kids too — no reactions, just glow."),
    (4, "Impressed", "Two weeks in and my skin is noticeably more even."),
    (3, "Decent", "Does the job, though I prefer a lighter texture for daytime."),
    (5, "Repurchasing forever", "Third bottle. My skin has never looked better."),
]

REVIEWERS = [  # (email, first_name)
    ("amaka.dev@example.com", "Amaka"), ("tunde.dev@example.com", "Tunde"),
    ("zainab.dev@example.com", "Zainab"), ("chidi.dev@example.com", "Chidi"),
    ("funke.dev@example.com", "Funke"), ("emeka.dev@example.com", "Emeka"),
]


def _placeholder_png(size, c1, c2, seed):
    """Soft two-tone vertical gradient with an off-centre blurred highlight — a
    premium, deliberately abstract stand-in for product photography (D4)."""
    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    img = Image.new("RGB", (w, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        row_color = tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))
        img.paste(row_color, (0, y, w, y + 1))
    rng = random.Random(seed)
    overlay = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(overlay)
    cx, cy = int(w * rng.uniform(0.3, 0.7)), int(h * rng.uniform(0.25, 0.5))
    r = int(min(w, h) * 0.45)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=70)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=r // 3))
    white = Image.new("RGB", (w, h), (255, 255, 255))
    img = Image.composite(white, img, overlay)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return ContentFile(buf.getvalue())


class Command(BaseCommand):
    help = "Seed a realistic DEV catalog (products, prices, stock, reviews, images)."

    def add_arguments(self, parser):
        parser.add_argument("--no-images", action="store_true",
                            help="Skip Pillow image generation (fast; used by tests).")

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("seed_dev_catalog is DEV-ONLY (requires DEBUG=True).")
        rng = random.Random(1313)
        countries = {c.code: c for c in Country.objects.all()}
        currencies = {c.code: c for c in Currency.objects.all()}

        # One warehouse serving every market (stock is country-scoped via warehouses).
        wh, _ = Warehouse.objects.get_or_create(
            name="Lagos Main (dev)",
            defaults={"location_country": "NG", "priority": 10},
        )
        wh.serves_countries.set(Country.objects.all())

        cats = {}
        for i, (name, slug, children) in enumerate(CATEGORIES):
            parent, _ = Category.objects.get_or_create(
                slug=slug, defaults={"name": name, "sort_order": i})
            cats[slug] = parent
            for j, child in enumerate(children):
                cslug = child.lower().replace(" ", "-")
                cats[cslug], _ = Category.objects.get_or_create(
                    slug=cslug, defaults={"name": child, "parent": parent, "sort_order": j})

        tags = {}
        for name, slug in TAGS:
            tags[slug], _ = Tag.objects.get_or_create(slug=slug, defaults={"name": name})
        brands = {}
        for name, slug in BRANDS:
            brands[slug], _ = Brand.objects.get_or_create(slug=slug, defaults={"name": name})

        # Reviewer users MUST be created through the manager's create_user(), which is
        # the only path that allocates the required unique `toke_id` (a plain
        # objects.create()/get_or_create leaves it "" and the 2nd reviewer collides).
        # Filter-first keeps this idempotent; create_user(password=None) => unusable pw.
        from django.contrib.auth import get_user_model
        User = get_user_model()
        users = []
        for email, first in REVIEWERS:
            u = User.objects.filter(email=email).first()
            if u is None:
                u = User.objects.create_user(email=email, first_name=first)
            users.append(u)

        # Price scoping: NGN->NG, GBP->GB, CAD->CA; USD rows use country=None so BOTH
        # the US market and ZZ (rest-of-world, USD) resolve the same row.
        price_country = {"NGN": countries.get("NG"), "GBP": countries.get("GB"),
                         "USD": None, "CAD": countries.get("CA")}

        all_products = []
        for idx, (name, slug, brand, cat, tag_slugs, sizes, amounts, on_sale, featured) in enumerate(PRODUCTS):
            product, _created = Product.objects.get_or_create(
                slug=slug,
                defaults=dict(
                    name=name, brand=brands[brand], status="active", is_featured=featured,
                    short_description=f"{name} — small-batch, science-backed care for melanin-rich skin.",
                    description=(
                        f"<p><strong>{name}</strong> is formulated with cold-pressed African "
                        "botanicals and clinically proven actives. Dermatologist reviewed, "
                        "cruelty free, and made for melanin-rich skin.</p>"
                        "<p>Free of parabens, sulphates and mineral oil.</p>"),
                    ingredients="Aqua, Butyrospermum Parkii (Shea) Butter, Niacinamide, "
                                "Glycerin, Simmondsia Chinensis (Jojoba) Seed Oil, Tocopherol.",
                    directions="Apply to clean skin morning and evening. Massage gently until absorbed.",
                    warnings="External use only. Patch-test before first use. Discontinue if irritation occurs.",
                    specs=[{"label": "Skin type", "value": "All, incl. sensitive"},
                           {"label": "Origin", "value": "Made in Nigeria"},
                           {"label": "Cruelty free", "value": "Yes"}],
                    faqs=[{"q": "Is it safe for sensitive skin?",
                           "a": "Yes — it is fragrance-light, but do your own patch test first."},
                          {"q": "When will I see results?",
                           "a": "Most customers report visible changes within 2-4 weeks of consistent use."}],
                    published_at=timezone.now() - timezone.timedelta(days=len(PRODUCTS) - idx),
                ),
            )
            all_products.append(product)
            product.categories.add(cats[cat])
            if cats[cat].parent:
                product.categories.add(cats[cat].parent)
            for t in tag_slugs:
                product.tags.add(tags[t])

            for pos, size in enumerate(sizes):
                sku = f"TOKE-{slug[:18].upper().replace('-', '')}-{size.upper().replace('/', '')}"
                variant, _ = ProductVariant.objects.get_or_create(
                    sku=sku,
                    defaults=dict(product=product, name=size,
                                  option_values={"Size": size},
                                  weight_grams=150 + pos * 150,
                                  is_default=(pos == 0), position=pos),
                )
                mult = Decimal("1") if pos == 0 else Decimal("1.6")  # bigger size ~1.6x
                for code, base in zip(("NGN", "GBP", "USD", "CAD"), amounts):
                    amount = (Decimal(base) * mult).quantize(Decimal("0.01"))
                    Price.objects.get_or_create(
                        variant=variant, currency=currencies[code],
                        country=price_country[code], starts_at=None,
                        defaults=dict(
                            amount=amount,
                            compare_at_amount=(amount * Decimal("1.25")).quantize(Decimal("0.01"))
                            if on_sale else None,
                        ),
                    )
                # Stock variety: idx 7 out of stock; 3/10/17 low stock; rest healthy.
                if idx == 7:
                    qty = 0
                elif idx in (3, 10, 17):
                    qty = rng.randint(2, 4)
                else:
                    qty = rng.randint(25, 180)
                StockItem.objects.get_or_create(
                    variant=variant, warehouse=wh,
                    defaults={"quantity": qty, "reserved": 0})

            if not opts["no_images"] and not product.images.exists():
                c1, c2 = PALETTES[idx % len(PALETTES)]
                for pos in range(2):  # two images -> card hover-swap + gallery
                    img = ProductImage(product=product, position=pos,
                                       alt=f"{name} — {'packaging' if pos else 'product'} shot")
                    img.image.save(f"{slug}-{pos}.png",
                                   _placeholder_png((900, 1200), c1, c2, seed=idx * 10 + pos),
                                   save=True)

            # Reviews: ~70% of products get 1-4 approved reviews (deterministic spread).
            if idx % 10 != 9:
                for r in range(rng.randint(1, 4)):
                    rating, title, body = REVIEW_BODIES[(idx + r) % len(REVIEW_BODIES)]
                    Review.objects.get_or_create(
                        product=product, user=users[(idx + r) % len(users)],
                        defaults=dict(rating=rating, title=title, body=body,
                                      status="approved"),
                    )
                recompute_product_rating(product)

        if not opts["no_images"]:
            root_cats = [c for c in cats.values() if c.parent is None]
            for i, cat in enumerate(root_cats):
                if not cat.image:
                    c1, c2 = PALETTES[i % len(PALETTES)]
                    cat.image.save(f"{cat.slug}.png",
                                   _placeholder_png((800, 800), c1, c2, seed=100 + i),
                                   save=True)

        # Homepage collections.
        for cslug, cname, picks in (
            ("best-sellers", "Best Sellers", [p for p in all_products if p.is_featured]),
            ("new-arrivals", "New Arrivals", all_products[-8:]),
            ("glow-naturally", "Glow Naturally", all_products[0:6]),
        ):
            col, _ = Collection.objects.get_or_create(
                slug=cslug, defaults={"name": cname,
                                      "description": f"{cname} — curated by Toke."})
            col.products.set(picks)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(all_products)} products, "
            f"{ProductVariant.objects.count()} variants, "
            f"{Review.objects.count()} reviews."))
