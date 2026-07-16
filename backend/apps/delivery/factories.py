import factory

from apps.delivery.models import DeliveryOption, DeliveryOptionRate


class DeliveryOptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryOption

    name = factory.Sequence(lambda n: f"Option {n}")
    kind = "manual"
    price = "1500.00"
    # currency must be passed by the test.
    min_days = 1
    max_days = 3
    is_active = True


class DeliveryOptionRateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryOptionRate

    option = factory.SubFactory(DeliveryOptionFactory)
    min_weight_g = 0
    max_weight_g = None
    price = "1500.00"
