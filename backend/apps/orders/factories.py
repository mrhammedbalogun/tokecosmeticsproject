import factory

from apps.orders.models import Order


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    email = factory.Sequence(lambda n: f"buyer{n}@x.com")
    status = "pending_payment"
    # number / country / currency / reservation_reference supplied by the test.
