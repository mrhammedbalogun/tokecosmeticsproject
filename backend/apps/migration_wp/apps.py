from django.apps import AppConfig


class MigrationWpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.migration_wp"
    verbose_name = "WordPress migration"
