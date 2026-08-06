from django.apps import AppConfig
from django.db.models.signals import m2m_changed, post_delete, post_save


class CmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cms"

    def ready(self) -> None:
        # Signals rather than viewset hooks so EVERY write path notifies the storefront —
        # admin API, Django admin, data migrations and shells alike. The receiver is a
        # no-op without REVALIDATE_SECRET; see apps/cms/revalidate.py.
        from apps.cms.models import (
            Banner,
            GoogleReview,
            GoogleReviewsMeta,
            HomepageSection,
            MenuItem,
            Page,
        )
        from apps.cms.revalidate import notify_cms_changed

        for model in (Banner, GoogleReview, GoogleReviewsMeta, HomepageSection, MenuItem, Page):
            post_save.connect(notify_cms_changed, sender=model, dispatch_uid=f"cms-reval-save-{model.__name__}")
            post_delete.connect(notify_cms_changed, sender=model, dispatch_uid=f"cms-reval-del-{model.__name__}")
        # Geo-targeting lives on an M2M; editing only the countries fires no post_save.
        m2m_changed.connect(
            notify_cms_changed, sender=Banner.countries.through, dispatch_uid="cms-reval-countries"
        )
