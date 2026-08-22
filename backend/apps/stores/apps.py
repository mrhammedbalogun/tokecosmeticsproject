from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class StoresConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.stores"

    def ready(self) -> None:
        # The storefront caches `/stores/places/` and `/stores/` for five minutes under
        # the "stores" tag. Without this, the first shop an operator adds stays invisible
        # on tokecosmetics.com/find-stores for up to five minutes after they save it,
        # which is exactly long enough to conclude the save failed (it happened, 2026-08-22).
        # Signals rather than viewset hooks so EVERY write path flushes — admin API,
        # Django admin, a shell. Same mechanism and same no-op-without-a-secret rule as
        # the CMS; see apps/cms/revalidate.py.
        from apps.stores.models import StoreLocation
        from apps.stores.revalidate import notify_stores_changed

        post_save.connect(notify_stores_changed, sender=StoreLocation,
                          dispatch_uid="stores-reval-save")
        post_delete.connect(notify_stores_changed, sender=StoreLocation,
                            dispatch_uid="stores-reval-delete")
