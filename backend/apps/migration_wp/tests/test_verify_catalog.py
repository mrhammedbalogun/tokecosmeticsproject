import csv

import pytest
from django.core.management import call_command

from apps.catalog.models import Product

pytestmark = pytest.mark.django_db


def test_verify_reports_counts_and_writes_worklists(artifact_path, tmp_path, capsys):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("verify_catalog", str(artifact_path), "--out-dir", str(tmp_path))

    assert "products" in capsys.readouterr().out

    rows = list(csv.DictReader((tmp_path / "pricing-todo.csv").open(encoding="utf-8")))
    assert {"sku", "product", "ngn_price", "gbp", "usd", "cad"} <= set(rows[0].keys())
    assert len(rows) == 8  # one per variant

    assert (tmp_path / "stock-todo.csv").exists()
    assert (tmp_path / "description-review.csv").exists()


def test_verify_flags_orphans(artifact_path, tmp_path, capsys):
    """A product removed from WordPress between runs must be reported, because
    update-or-skip never deletes."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    Product.objects.create(name="Ghost", slug="ghost", legacy_source="wp_ng", legacy_wp_id=999)
    call_command("verify_catalog", str(artifact_path), "--out-dir", str(tmp_path))
    assert "ghost" in capsys.readouterr().out


def test_verify_asserts_no_wp_content_urls(artifact_path, tmp_path, capsys):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    p = Product.objects.get(slug="toke-coconut-oil")
    p.description = '<img src="https://tokecosmetics.com/wp-content/uploads/x.jpg">'
    p.save(update_fields=["description"])

    call_command("verify_catalog", str(artifact_path), "--out-dir", str(tmp_path))
    assert "wp-content" in capsys.readouterr().out


def test_verify_reports_unknown_weight_count(artifact_path, tmp_path, capsys):
    """Unknown weight silently becomes 0 in delivery pricing, so the count must
    be visible in the worklist rather than buried."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("verify_catalog", str(artifact_path), "--out-dir", str(tmp_path))
    out = capsys.readouterr().out.lower()
    assert "weight" in out


def test_description_review_marks_missing_copy(artifact_path, tmp_path):
    """ingredients/directions/warnings have no WooCommerce source field."""
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("verify_catalog", str(artifact_path), "--out-dir", str(tmp_path))
    rows = {
        r["slug"]: r
        for r in csv.DictReader((tmp_path / "description-review.csv").open(encoding="utf-8"))
    }
    assert rows["toke-scented-shea-butter"]["ingredients"] == "MISSING"
