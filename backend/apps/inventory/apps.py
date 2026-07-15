from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.inventory"

    def ready(self):
        from apps.inventory import signals  # noqa: F401  (catalog cache invalidation on stock change)
