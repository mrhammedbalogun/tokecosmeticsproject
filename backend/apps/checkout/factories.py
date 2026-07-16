import factory

from apps.checkout.models import Coupon


class CouponFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Coupon

    code = factory.Sequence(lambda n: f"SAVE{n}")
    type = "percent"
    value = "10.00"
    is_active = True
