"""Reshape the category tree into the approved Shop by Category menu (2026-09-10).

    manage.py rebuild_shop_menu            # prints the plan, writes nothing
    manage.py rebuild_shop_menu --apply    # writes it

WHY A COMMAND AND NOT A DATA MIGRATION
--------------------------------------
A migration would run identically against dev, CI and production, and these rows are not
the same in any two of them: production carries 40 WordPress-era categories, `seed_dev_
catalog` invents its own, and CI has none. The mapping below is written against
production's actual rows, so it has to be a thing somebody RUNS, having read the plan it
prints, against the database they mean. Dry-run is the default for that reason.

IDEMPOTENT. Running it twice is a no-op: every step is "make it so", not "change it".
That matters because the first real run happens on live data and the second happens when
somebody re-runs it to check.

NOTHING IS DELETED. Categories outside the new menu are DEACTIVATED (`is_active=False`),
which drops them from the tree endpoint and the menu while keeping every
product-to-category row they hold. If a decision here turns out wrong — "Men Care" was
worth keeping, say — the fix is a checkbox, not a re-import.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import Category, Product


@dataclass
class Node:
    """One row of the target menu.

    `reuse` names the slugs this row may adopt, best first: adopting an existing row keeps
    its product assignments (production's "Hair Care" holds 18) and its URL. `merge` names
    rows whose products move ONTO this row before they are retired — three separate
    "Skin Care" rows became one, and their assignments are unioned rather than dropped.
    """

    name: str
    slug: str
    reuse: tuple[str, ...] = ()
    merge: tuple[str, ...] = ()
    assignable: bool = True
    children: list["Node"] = field(default_factory=list)


# ── The approved menu, in menu order ────────────────────────────────────────────────────
#
# Order here IS `sort_order` (10, 20, 30 … leaving room to insert without renumbering).
#
# "Shop By Edit" is ABSENT ON PURPOSE. Its five entries — Best Sellers, New Arrivals,
# Promo, Combo Deals, Travel Sizes — are computed listings and a link to an existing page,
# not sets a product gets filed into, so they live in the storefront's menu code
# (`lib/shop-menu.ts`) rather than as rows here. A category nobody can assign to, whose
# page would show whatever happened to be filed on it, is a trap.
MENU: list[Node] = [
    Node("Baby/Kids & Care", "baby-kids-care",
         reuse=("baby-care",),
         merge=("baby-care-shop-by-category", "kids", "kids-care")),
    Node("Hair Care", "hair-care",
         reuse=("hair-care",),
         merge=("hair-care-shop-by-category",)),
    Node("Skin Care", "skin-care",
         reuse=("skin-care",),
         merge=("skin-care-2",)),
    Node("Facial Care", "facial-care",
         reuse=("facial-care", "facials"),
         merge=("facial-set",)),
    Node("Shop By Skin Concerns", "shop-by-skin-concerns",
         reuse=("shop-by-skin-concern",), assignable=False, children=[
             Node("Acne", "acne"),
             Node("Dry Skin", "dry-skin", reuse=("dry-skin",)),
             Node("Hyperpigmentation", "hyperpigmentation", reuse=("hyperpigmentation",)),
             Node("Oily Skin", "oily-skin", reuse=("oily-skin",)),
         ]),
    Node("Travel Sizes", "travel-sizes",
         reuse=("travel-size",),
         merge=("travel-size-shop-by-category", "travel-size-shop-by-edit")),
    Node("Shop By Skin Tone", "shop-by-skin-tone", assignable=False, children=[
        Node("Fair Skin", "fair-skin", reuse=("fair-skin",)),
        Node("Caramel Skin", "caramel-skin", reuse=("caramel-skin",)),
        Node("Deep Skin", "deep-skin"),
    ]),
]


class Command(BaseCommand):
    help = "Reshape the category tree into the Shop by Category menu (dry-run by default)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the changes. Without it, nothing is saved.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        self.log: list[str] = []
        # Instance state, not the class attribute it started as: a class-level set is
        # shared by every invocation in a process, so a second call in the same test run
        # would find every row "already claimed" and create duplicates instead of
        # adopting them.
        self._claimed: set[int] = set()
        # old slug → new slug, for every row this run renames or merges away. Feeds
        # `_fix_banners`, so the links that have to change and the record of what changed
        # cannot drift apart.
        self._moved: dict[str, str] = {}
        # One transaction either way, rolled back on a dry run: the plan is then computed
        # against the same intermediate states the real run would see, so what it prints
        # is what would happen — not an optimistic guess made against untouched rows.
        try:
            with transaction.atomic():
                kept = self._rebuild()
                self._retire(kept)
                self._fix_banners()
                self._summarise()
                if not apply:
                    raise _DryRun()
        except _DryRun:
            pass

        for line in self.log:
            self.stdout.write(line)
        self.stdout.write("")
        if apply:
            self.stdout.write(self.style.SUCCESS("Applied."))
        else:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — nothing was written. Re-run with --apply to commit."
            ))

    # ── steps ───────────────────────────────────────────────────────────────────────────

    def _rebuild(self) -> set[int]:
        """Create/adopt every menu row in order. Returns the pks that must stay active."""
        kept: set[int] = set()
        order = 0
        for node in MENU:
            order += 10
            row = self._upsert(node, parent=None, sort_order=order)
            kept.add(row.pk)
            child_order = 0
            for child in node.children:
                child_order += 10
                kept.add(self._upsert(child, parent=row, sort_order=child_order).pk)
        return kept

    def _upsert(self, node: Node, parent: Category | None, sort_order: int) -> Category:
        row = self._adopt(node)
        if row is None:
            row = Category(slug=node.slug)
            self.log.append(f"CREATE   {node.name}  ({node.slug})")
        else:
            changes = []
            if row.name != node.name:
                changes.append(f"name {row.name!r}→{node.name!r}")
            if row.slug != node.slug:
                # Slug moves are why the storefront ships a redirect table: the old URL is
                # indexed, and a 308 is the difference between a moved page and a 404.
                changes.append(f"slug {row.slug}→{node.slug}")
                self._moved[row.slug] = node.slug
            if row.parent_id != (parent.pk if parent else None):
                changes.append(f"parent →{parent.slug if parent else 'root'}")
            if not row.is_active:
                changes.append("reactivate")
            if row.is_assignable != node.assignable:
                changes.append(f"assignable →{node.assignable}")
            verb = "REUSE   " if changes else "KEEP    "
            detail = f"  [{', '.join(changes)}]" if changes else ""
            self.log.append(
                f"{verb} {node.name}  ({row.slug}, {row.products.count()} products){detail}"
            )

        self._free_slug(node.slug, row)
        row.name = node.name
        row.slug = node.slug
        row.parent = parent
        row.is_active = True
        row.is_assignable = node.assignable
        row.sort_order = sort_order
        row.save()

        for merge_slug in node.merge:
            self._merge_into(row, merge_slug)

        if not node.assignable:
            # A heading holds no products, and once `is_assignable=False` the admin's
            # product editor stops offering it — so anything already filed here would be
            # stuck: visible on the group page, with no checkbox anywhere to remove it.
            # Its children are what a shopper is choosing between.
            stuck = row.products.count()
            if stuck:
                self.log.append(
                    f"         └ clearing {stuck} product(s) filed on this heading"
                )
                row.products.clear()
        return row

    def _adopt(self, node: Node) -> Category | None:
        """The existing row this node should become, or None to create one.

        Tries the target slug first so a second run adopts what the first run wrote, then
        the legacy slugs in the order given. Any row whose slug is taken by ANOTHER
        adopted node is skipped, which is what stops two nodes fighting over one row.
        """
        for slug in (node.slug, *node.reuse):
            row = Category.objects.filter(slug=slug).first()
            if row is None:
                continue
            if row.pk in self._claimed:
                continue
            self._claimed.add(row.pk)
            return row
        return None

    def _free_slug(self, slug: str, keep: Category) -> None:
        """Take `slug` off whatever row is holding it, so `keep` can have it.

        `Category.slug` is UNIQUE, so without this a rename collides mid-run and the
        command dies on an IntegrityError. The dispossessed row is on its way to being
        retired anyway (nothing adopted it, or another node did), and it keeps a
        recognisable slug so the table still reads clearly afterwards.
        """
        holder = Category.objects.filter(slug=slug).exclude(pk=keep.pk).first()
        if holder is None:
            return
        freed = f"{slug}-legacy"
        n = 2
        while Category.objects.filter(slug=freed).exclude(pk=holder.pk).exists():
            freed, n = f"{slug}-legacy-{n}", n + 1
        self.log.append(
            f"         └ freeing slug {slug!r} from {holder.name!r} (pk {holder.pk}) → {freed}"
        )
        Category.objects.filter(pk=holder.pk).update(slug=freed)

    def _merge_into(self, target: Category, source_slug: str) -> None:
        """Move a duplicate's products onto `target`, then leave it for `_retire`.

        UNION, not move: a product already in both is unaffected, and `add` on a
        ManyToMany is idempotent, so a second run costs nothing. The source keeps its own
        rows too — harmless, since it is about to be deactivated, and it means a mistaken
        merge can be undone by reactivating the source rather than by re-deriving who was
        in it.
        """
        source = Category.objects.filter(slug=source_slug).first()
        if source is None or source.pk == target.pk:
            return
        products = list(source.products.all())
        already = set(target.products.values_list("pk", flat=True))
        added = [p for p in products if p.pk not in already]
        if added:
            target.products.add(*added)
        self._moved[source.slug] = target.slug
        self.log.append(
            f"         └ merge {source.name!r} ({source.slug}): "
            f"{len(products)} product(s), {len(added)} new to {target.slug}"
        )

    def _retire(self, kept: set[int]) -> None:
        """Deactivate and unparent everything outside the new menu.

        `parent=None` as well as `is_active=False`: a retired row left pointing at a live
        heading still shows up in `Category.children` for anything that forgets to filter
        on `is_active` — the admin's tree view does exactly that — so it would read as a
        child of a menu group it is no longer part of.
        """
        stale = Category.objects.exclude(pk__in=kept).filter(is_active=True)
        for row in stale.order_by("name"):
            self.log.append(
                f"RETIRE   {row.name}  ({row.slug}, {row.products.count()} products kept)"
            )
        stale.update(is_active=False, parent=None)

    def _fix_banners(self) -> None:
        """Repoint homepage tiles whose category URL this run just moved.

        The four "Shop by category" tiles are CMS banners with a literal `cta_url`, and two
        of production's point at slugs this rebuild renames (`/category/skin-care-2`,
        `/category/kids`). The storefront's redirect table would catch them, but a tile on
        the homepage should not need catching — it is the most-clicked link on the site,
        and a 308 there is a bug that merely does not show.

        ONLY WHAT THIS RUN BROKE. A tile pointing somewhere odd for its own reasons — the
        one aimed at `/` — is left alone and reported: fixing that is a decision about what
        the tile should say, not a consequence of renaming a category.
        """
        from apps.cms.models import Banner

        for banner in Banner.objects.all():
            url = banner.cta_url or ""
            if not url.startswith("/category/"):
                continue
            old = url[len("/category/"):].strip("/")
            new = self._moved.get(old)
            if not new or new == old:
                continue
            fixed = f"/category/{new}"
            self.log.append(
                f"BANNER   {banner.title!r}: {url} → {fixed}"
            )
            Banner.objects.filter(pk=banner.pk).update(cta_url=fixed)

    def _summarise(self) -> None:
        """What the admin has to do next, which is the point of running this.

        The uncategorised count is the work list: with the old rows retired, a product
        whose only categories were "Men Care" and "Skincare Sets" now sits in none of the
        menu, so it is reachable from All Products and search but from no shelf. Nothing
        breaks — but somebody has to file it, and knowing the number beats discovering it.
        """
        self.log.append("")
        self.log.append("── The menu now ──────────────────────────────────────────────")
        for root in Category.objects.filter(
            is_active=True, parent__isnull=True
        ).order_by("sort_order", "name"):
            kind = "" if root.is_assignable else "  (heading)"
            self.log.append(f"{root.name}{kind} — {root.products.count()} products")
            for child in root.children.filter(is_active=True).order_by("sort_order", "name"):
                self.log.append(f"   ├ {child.name} — {child.products.count()} products")

        filed = Product.objects.filter(
            categories__is_active=True, categories__is_assignable=True
        ).distinct().count()
        total = Product.objects.count()
        self.log.append("")
        self.log.append(
            f"{filed} of {total} products sit in at least one menu category; "
            f"{total - filed} need filing."
        )


class _DryRun(Exception):
    """Rolls the transaction back at the end of a dry run."""
