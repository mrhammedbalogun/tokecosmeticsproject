import factory

from apps.payments.models import Payment


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment

    gateway = "bank_transfer"
    amount = "1000.00"
    status = "initiated"
    idempotency_key = factory.Sequence(lambda n: f"idem-{n}")
    # order / currency supplied by the test.
