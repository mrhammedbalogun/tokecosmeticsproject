from django.apps import AppConfig


class CombosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.combos"

    def ready(self):
        from apps.combos import signals  # noqa: F401  (cache invalidation receivers)
