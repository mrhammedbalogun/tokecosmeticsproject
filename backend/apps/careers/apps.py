from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class CareersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.careers"

    def ready(self) -> None:
        # Without this, the first role somebody opens stays invisible on
        # tokecosmetics.com/careers until the tag expires — long enough to conclude the
        # save failed, which is exactly what happened to the store directory on
        # 2026-08-22. Signals rather than viewset hooks so EVERY write path flushes:
        # the admin API, the seed command, the Django admin and a shell.
        #
        # `JobApplication` is deliberately NOT connected. Nothing an applicant does
        # changes the public page, and firing a revalidation per application would make
        # the storefront's cache churn in proportion to how well the advert is doing.
        from apps.careers.models import JobLocation, JobPosting
        from apps.careers.revalidate import notify_careers_changed

        for model in (JobPosting, JobLocation):
            post_save.connect(
                notify_careers_changed, sender=model,
                dispatch_uid=f"careers-reval-save-{model.__name__}",
            )
            post_delete.connect(
                notify_careers_changed, sender=model,
                dispatch_uid=f"careers-reval-delete-{model.__name__}",
            )
