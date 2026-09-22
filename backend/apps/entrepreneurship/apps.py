from django.apps import AppConfig
from django.db.models.signals import post_save


class EntrepreneurshipConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.entrepreneurship"
    verbose_name = "Student Entrepreneurship Program"

    def ready(self) -> None:
        # Flipping the intake shut must reach the public page NOW. Without this, the
        # form stays on tokecosmetics.com until the tag expires — long enough to collect
        # applications after somebody deliberately stopped taking them, which is the one
        # failure this setting exists to prevent.
        #
        # A SIGNAL rather than a viewset hook so EVERY write path flushes: the admin API,
        # the Django admin, a data migration and a shell.
        #
        # `ProgramApplication` is deliberately NOT connected. Nothing an applicant does
        # changes the public page, and firing a revalidation per application would make
        # the storefront's cache churn in proportion to how well the page is doing.
        from apps.entrepreneurship.models import ProgramSettings
        from apps.entrepreneurship.revalidate import notify_programme_changed

        post_save.connect(
            notify_programme_changed,
            sender=ProgramSettings,
            dispatch_uid="programme-reval-save",
        )
