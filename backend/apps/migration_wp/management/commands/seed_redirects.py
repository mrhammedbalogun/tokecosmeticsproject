"""Seed `core.Redirect` from a URL-space artifact (Plan-24), and import the editorial
content those redirects point at.

Both halves live in one command on purpose: a redirect to a CMS page that does not exist
is worse than a 404 — the visitor gets a real page that is blank. Running them together
means the report can say, in one place, which targets are missing.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import Category
from apps.cms.models import Page
from apps.core.models import Redirect
from apps.core.redirects import bump_version
from apps.migration_wp.transform_urls import (
    CATEGORY_FALLBACK,
    build_redirects,
    shadowed_routes,
)


class Command(BaseCommand):
    help = "Seed legacy URL redirects (and optionally the editorial pages they point at)."

    def add_arguments(self, parser):
        parser.add_argument("artifact", help="path to the JSON from extract_wp_urls")
        parser.add_argument("--dry-run", action="store_true", help="report only")
        parser.add_argument(
            "--with-content",
            action="store_true",
            help=(
                "also import post/help/article bodies as CMS pages. Without this the "
                "redirects are seeded but 50 of them point at pages that do not exist yet."
            ),
        )
        parser.add_argument(
            "--publish",
            action="store_true",
            help=(
                "publish imported pages immediately. Default is DRAFT, so a human reads "
                "the converted markup before it is public."
            ),
        )

    def handle(self, *args, **options):
        path = Path(options["artifact"])
        if not path.is_file():
            raise CommandError(f"No such artifact: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))

        dry_run = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no writes will be made"))

        rows, conflicts = build_redirects(data)

        with transaction.atomic():
            content = (
                self._import_content(data, publish=options["publish"])
                if options["with_content"]
                else {"created": 0, "updated": 0, "skipped_no_body": 0}
            )
            stats = self._seed(rows)
            missing = self._missing_targets(rows)
            if dry_run:
                transaction.set_rollback(True)
            else:
                bump_version()

        self._report(rows, conflicts, stats, content, missing, dry_run)

    # ── redirects ────────────────────────────────────────────────────────────────────────

    def _seed(self, rows) -> dict:
        """Idempotent on `old_path`, which is the unique column. A re-run refreshes the
        target rather than creating a duplicate or raising."""
        created = updated = unchanged = 0
        # Categories that did not survive Plan-21 point at /products rather than at a
        # /category/<slug> that 404s — a category URL with inbound links is a shopper
        # looking for products, and the full listing beats nothing.
        live_categories = set(Category.objects.values_list("slug", flat=True))

        for row in rows:
            new_path = row["new_path"]
            if row["source"] == "category":
                slug = row["old_path"].rsplit("/", 1)[-1]
                if slug not in live_categories:
                    new_path = CATEGORY_FALLBACK

            existing = Redirect.objects.filter(old_path=row["old_path"]).first()
            if existing is None:
                Redirect.objects.create(
                    old_path=row["old_path"],
                    new_path=new_path,
                    status_code=row["status_code"],
                )
                created += 1
            elif (existing.new_path, existing.status_code) != (new_path, row["status_code"]):
                existing.new_path = new_path
                existing.status_code = row["status_code"]
                # `hits` is deliberately NOT reset: it measures the old URL's traffic, and
                # that is still true after the target is corrected.
                existing.save(update_fields=["new_path", "status_code"])
                updated += 1
            else:
                unchanged += 1
        return {"created": created, "updated": updated, "unchanged": unchanged}

    def _missing_targets(self, rows) -> list[str]:
        """Redirects pointing at `/page/<slug>` where no PUBLISHED CMS page exists.

        This is the check that makes ruling 4 real. A 301 to a blank page is a worse
        experience than a 404: the visitor believes they arrived somewhere. It is also the
        outstanding "eleven pages of policy text" item, surfaced as a list rather than as a
        sentence in a plan nobody re-reads.
        """
        published = set(
            Page.objects.filter(status=Page.PUBLISHED).values_list("slug", flat=True)
        )
        return sorted(
            r["new_path"]
            for r in rows
            if r["new_path"].startswith("/page/")
            and r["new_path"][len("/page/"):] not in published
        )

    # ── editorial content ────────────────────────────────────────────────────────────────

    def _import_content(self, data: dict, *, publish: bool) -> dict:
        """WordPress post bodies -> `cms.Page`, sanitised on the way in.

        Sanitising is not done here: `Page.save()` already runs `body_source` through
        `cms.sanitize.clean_html` on every save (`cms/models.py:64`), which is the same
        path an admin-authored page takes. Re-implementing it here would be a second trust
        boundary that could drift from the first.

        DRAFT by default. This markup is Elementor output and WordPress shortcodes; a human
        should look at what survived the allow-list before it is public.
        """
        created = updated = skipped = 0
        for kind in ("posts", "helps"):
            for row in data.get(kind, []):
                slug = (row.get("slug") or "").strip()
                body = (row.get("post_content") or "").strip()
                if not slug:
                    continue
                if not body:
                    # An empty body would publish a blank page — the exact failure
                    # _missing_targets exists to prevent, arriving by another door.
                    skipped += 1
                    continue

                page, is_new = Page.objects.get_or_create(
                    slug=slug,
                    defaults={"title": (row.get("post_title") or slug)[:200]},
                )
                if not is_new and page.body_source:
                    # Never overwrite a page a human has since edited. Same rule as the
                    # customer importer's password handling, for the same reason.
                    continue
                page.title = (row.get("post_title") or slug)[:200]
                page.body_source = body
                page.status = Page.PUBLISHED if publish else Page.DRAFT
                page.save()
                created += is_new
                updated += not is_new
        return {"created": created, "updated": updated, "skipped_no_body": skipped}

    # ── report ───────────────────────────────────────────────────────────────────────────

    def _report(self, rows, conflicts, stats, content, missing, dry_run) -> None:
        self.stdout.write(f"  redirects in artifact  {len(rows)}")
        for key, value in stats.items():
            self.stdout.write(f"  {key.ljust(21)}  {value}")
        for key, value in content.items():
            self.stdout.write(f"  content {key.ljust(13)}  {value}")

        if conflicts:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                f"{len(conflicts)} duplicate path(s) — WordPress had two rows at one URL:"
            ))
            for c in conflicts:
                self.stdout.write(
                    f"  {c['old_path']}: kept the {c['kept']}, dropped the {c['dropped']} "
                    f"(would have gone to {c['dropped_target']})"
                )

        shadowed = shadowed_routes(rows)
        if shadowed:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(
                "These old paths are ALREADY real storefront routes, so their rows can "
                "never fire. Harmless, but they are a lie in the table:"
            ))
            for p in shadowed:
                self.stdout.write(f"  {p}")

        if missing:
            self.stdout.write("")
            self.stdout.write(self.style.ERROR(
                f"{len(missing)} redirect(s) point at a CMS page that is not published. "
                "A 301 to a blank page is worse than a 404 — write the copy, or unpublish "
                "the redirect:"
            ))
            for p in missing:
                self.stdout.write(f"  {p}")

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{'Would seed' if dry_run else 'Seeded'} {stats['created']} new redirects."
        ))
