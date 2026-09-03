"""factory_boy factories for combo test data. Import only from tests."""
import factory

from apps.combos.models import Combo, ComboItem


class ComboFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Combo

    name = factory.Sequence(lambda n: f"Combo {n}")
    slug = factory.Sequence(lambda n: f"combo-{n}")
    status = "active"


class ComboItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ComboItem

    combo = factory.SubFactory(ComboFactory)
    quantity = 1
