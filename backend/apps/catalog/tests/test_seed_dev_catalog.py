"""The seed command must produce a browsable catalog and be idempotent."""
import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.catalog.models import Collection, Product
from apps.core.models import Country
from apps.inventory.services import available_for_country
from apps.pricing.services import resolve_price


@pytest.mark.django_db
class TestSeedDevCatalog:
    # NOTE: override_settings(DEBUG=True) is applied per-method rather than as a class
    # decorator — Django rejects class-level override_settings unless the class subclasses
    # SimpleTestCase, and this suite is pytest-django (plain classes). Same intent: the
    # command runs under DEBUG=True; the refusal test forces DEBUG=False.
    def _run(self):
        call_command("seed_dev_catalog", "--no-images")  # images skipped in tests (slow)

    @override_settings(DEBUG=True)  # the command refuses to run outside DEBUG
    def test_seeds_a_realistic_catalog(self):
        self._run()
        products = Product.objects.filter(status="active")
        assert products.count() >= 24

        ng = Country.objects.get(code="NG")
        gb = Country.objects.get(code="GB")
        us = Country.objects.get(code="US")
        ca = Country.objects.get(code="CA")

        priced_everywhere = 0
        with_stock = 0
        for p in products.prefetch_related("variants"):
            v = p.variants.filter(is_active=True).first()
            assert v is not None, f"{p.slug} has no variant"
            if all(resolve_price(v, c) is not None for c in (ng, gb, us, ca)):
                priced_everywhere += 1
            if available_for_country(v, ng) > 0:
                with_stock += 1
        assert priced_everywhere >= 24, "every seeded product is priced in all 4 currencies"
        assert with_stock >= 20, "most products in stock in NG"

        # Collections used by the homepage exist and are populated.
        for slug in ("best-sellers", "new-arrivals", "glow-naturally"):
            c = Collection.objects.get(slug=slug)
            assert c.products.count() >= 4, f"collection {slug} too small"

        # Reviews fed the denormalised rating.
        assert products.filter(rating_count__gt=0).count() >= 10

    @override_settings(DEBUG=True)
    def test_is_idempotent(self):
        self._run()
        first = Product.objects.count()
        self._run()
        assert Product.objects.count() == first

    @override_settings(DEBUG=False)
    def test_refuses_outside_debug(self):
        from django.core.management.base import CommandError
        with pytest.raises(CommandError):
            call_command("seed_dev_catalog", "--no-images")
