import pytest
from django.core.management import call_command

from apps.catalog.models import Category, Tag

pytestmark = pytest.mark.django_db


def test_imports_categories_preserving_slug_and_legacy_id(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")

    soaps = Category.objects.get(slug="body-soaps")
    assert soaps.name == "Body Soaps"
    assert soaps.legacy_wp_id == 21
    assert soaps.parent is None
    assert soaps.description == "Soaps for the body"
    assert Category.objects.count() == 2


def test_imports_tags(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert Tag.objects.filter(slug="bestseller").exists()


def test_dry_run_writes_nothing(artifact_path):
    call_command("import_catalog", str(artifact_path), "--dry-run")
    assert Category.objects.count() == 0
    assert Tag.objects.count() == 0


def test_rerunning_does_not_duplicate_categories(artifact_path):
    call_command("import_catalog", str(artifact_path), "--skip-media")
    call_command("import_catalog", str(artifact_path), "--skip-media")
    assert Category.objects.count() == 2
    assert Category.objects.filter(legacy_wp_id=21).count() == 1


def test_import_catalog_never_touches_mariadb():
    """The extract/import split is a security boundary: import must not be able
    to reach the WordPress database even if credentials were present."""
    import inspect

    from apps.migration_wp.management.commands import import_catalog

    source = inspect.getsource(import_catalog)
    assert "wp_reader" not in source
    assert "pymysql" not in source
