from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class MarketingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.marketing"

    def ready(self) -> None:
        # The storefront caches `/marketing/config/` under the "marketing" tag, and what
        # that payload carries is the tracking master switch, the consent policy and the
        # pixel ids. All three are things an Owner turns off or corrects BECAUSE
        # something is wrong, so waiting out a TTL is the one behaviour they must not
        # have. See apps/marketing/revalidate.py.
        #
        # Signals rather than hooks on the two admin views so EVERY write path flushes —
        # the admin API, the Django admin, a shell. The receiver is a no-op without
        # REVALIDATE_SECRET; same mechanism as the CMS (apps/cms/revalidate.py).
        #
        # `ensure_channel_rows()` cannot trigger this: it seeds placeholder channels with
        # `bulk_create`, which sends no signals — and those rows carry no pixel id, so the
        # public serialiser excludes them anyway. A GET of the admin screen therefore
        # flushes nothing, which is the intent.
        from apps.marketing.models import MarketingChannel, MarketingSettings
        from apps.marketing.revalidate import (
            notify_marketing_changed,
            notify_marketing_settings_changed,
        )

        # MarketingSettings: post_save only, and its own receiver because that one has to
        # ignore `created` — `load()` materialises the row on a plain public GET. It is a
        # pk=1 singleton that `load()` recreates and nothing in the codebase deletes,
        # exactly like BusinessDecisions.
        post_save.connect(notify_marketing_settings_changed, sender=MarketingSettings,
                          dispatch_uid="marketing-settings-reval-save")

        # MarketingChannel: both. The admin API offers no delete (the row set IS the
        # adapter set), but the Django admin and a shell do, and a removed channel has to
        # stop being served to browsers.
        post_save.connect(notify_marketing_changed, sender=MarketingChannel,
                          dispatch_uid="marketing-channel-reval-save")
        post_delete.connect(notify_marketing_changed, sender=MarketingChannel,
                            dispatch_uid="marketing-channel-reval-delete")
