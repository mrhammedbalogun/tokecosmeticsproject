from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"

    def ready(self):
        # Registers the gateway-configuration system check (payments.W001).
        from apps.payments import checks  # noqa: F401
