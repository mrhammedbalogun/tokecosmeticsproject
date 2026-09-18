from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'

    def ready(self) -> None:
        # The storefront caches `/referrals/terms/` for an HOUR under the
        # "referral-terms" tag, and /affiliates advertises the two percentages it
        # returns. Without this flush, changing the commission rate on the admin's
        # Business Decisions page would leave the public page promising the old number
        # while the checkout already paid the new one — which is precisely the drift
        # those numbers are served from the API to prevent.
        #
        # A signal rather than a hook on the admin view so EVERY write path flushes:
        # the API, the Django admin, a shell. Same mechanism and same
        # no-op-without-a-secret rule as the CMS; see apps/cms/revalidate.py.
        #
        # No post_delete: the row is a pk=1 singleton that `load()` recreates, and
        # nothing in the codebase deletes it.
        from apps.core.models import BusinessDecisions, Redirect, Region
        from apps.core.revalidate import (
            notify_decisions_changed,
            notify_redirects_changed,
            notify_regions_changed,
        )

        post_save.connect(notify_decisions_changed, sender=BusinessDecisions,
                          dispatch_uid="business-decisions-reval-save")

        # Both tables are read by the storefront through long-lived caches — an hour for
        # the redirect lookup, a DAY for regions — and both are edited rarely and by hand.
        # That combination is the one where a flush earns the most: the TTLs are only
        # affordable because an edit does not have to wait them out.
        for model, receiver_fn, name in (
            (Redirect, notify_redirects_changed, "redirects"),
            (Region, notify_regions_changed, "regions"),
        ):
            post_save.connect(receiver_fn, sender=model, dispatch_uid=f"{name}-reval-save")
            post_delete.connect(receiver_fn, sender=model, dispatch_uid=f"{name}-reval-delete")
