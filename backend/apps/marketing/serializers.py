"""Public serialisers: what the storefront is allowed to know about the tracking setup.

The rule this file exists to enforce: **only what the browser would learn anyway.** A
pixel id appears in the HTML of every page and in any network trace, so publishing it
costs nothing. Everything else — access tokens, the test event code, whether a channel's
server half is on — is server business, and a public endpoint that leaked the test event
code would be handing anyone a way to divert events into a test console.
"""
from rest_framework import serializers

from apps.marketing.models import MarketingChannel, MarketingSettings


class PublicChannelSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketingChannel
        fields = ["code", "pixel_id", "secondary_id"]


class PublicMarketingConfigSerializer(serializers.ModelSerializer):
    channels = serializers.SerializerMethodField()

    class Meta:
        model = MarketingSettings
        fields = ["tracking_enabled", "consent_version", "consent_required_countries",
                  "channels"]

    def get_channels(self, obj) -> list[dict]:
        """Only channels that are on, have a browser tag switched on, and have an id to
        load it with. A channel missing any of the three would render a script tag that
        cannot work, and an empty pixel id in the page source is how a broken setup gets
        mistaken for a working one."""
        if not obj.tracking_enabled:
            return []
        rows = MarketingChannel.objects.filter(
            is_enabled=True, browser_enabled=True
        ).exclude(pixel_id="")
        return PublicChannelSerializer(rows, many=True).data
