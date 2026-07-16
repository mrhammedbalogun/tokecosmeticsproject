from django.db import models

from apps.core.models import TimeStampedModel


class DeliveryOption(TimeStampedModel):
    KIND_CHOICES = [("manual", "Manual"), ("carrier", "Carrier API")]

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="manual")
    carrier_code = models.CharField(max_length=20, blank=True)  # "dhl", "gig" — Plan-32
    price = models.DecimalField(max_digits=12, decimal_places=2)  # flat price (common case)
    currency = models.ForeignKey("core.Currency", on_delete=models.PROTECT)
    free_over = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    min_days = models.PositiveSmallIntegerField()
    max_days = models.PositiveSmallIntegerField()
    countries = models.ManyToManyField("core.Country", blank=True, related_name="delivery_options")
    regions = models.ManyToManyField("core.Region", blank=True, related_name="delivery_options")
    is_active = models.BooleanField(default=True)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.currency_id})"


class DeliveryOptionRate(models.Model):
    """Optional weight tiers. If an option has no rates, its flat `price` applies."""

    option = models.ForeignKey(DeliveryOption, on_delete=models.CASCADE, related_name="rates")
    min_weight_g = models.IntegerField(default=0)
    max_weight_g = models.IntegerField(null=True, blank=True)  # null = no upper bound
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["min_weight_g"]

    def __str__(self) -> str:
        upper = self.max_weight_g if self.max_weight_g is not None else "∞"
        return f"{self.option_id}: {self.min_weight_g}-{upper}g @ {self.price}"
