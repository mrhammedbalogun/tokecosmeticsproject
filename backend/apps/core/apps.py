from django.apps import AppConfig
from django.db.models.signals import post_save


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
        from apps.core.models import BusinessDecisions
        from apps.core.revalidate import notify_decisions_changed

        post_save.connect(notify_decisions_changed, sender=BusinessDecisions,
                          dispatch_uid="business-decisions-reval-save")
