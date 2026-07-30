from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'

    def ready(self):
        from . import signals  # noqa: F401 — connects the auth security-event receivers
        from . import checks  # noqa: F401 — registers the staff-role check (accounts.W001)
