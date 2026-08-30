"""The one public endpoint: what the storefront needs to render its tags.

Anonymous and cacheable. Deliberately NOT cached here — the storefront caches it the way
it caches every other configuration read (a revalidating fetch), and a second cache in
Django would mean two invalidation stories for one value.
"""
from django.http import HttpResponse
from django.views.decorators.cache import cache_control
from rest_framework import generics, permissions

from apps.core.models import Country
from apps.marketing.feed import build_feed
from apps.marketing.models import MarketingSettings
from apps.marketing.serializers import PublicMarketingConfigSerializer


class MarketingConfigView(generics.RetrieveAPIView):
    """`GET /api/v1/marketing/config/` — the pixel ids to load, the consent policy to
    apply, and the master switch. Never a credential; see the serializer."""

    permission_classes = [permissions.AllowAny]
    serializer_class = PublicMarketingConfigSerializer

    def get_object(self):
        return MarketingSettings.load()


@cache_control(max_age=3600, public=True)
def product_feed(request):
    """`GET /api/v1/marketing/feed/products.xml?country=NG` — the catalogue as a Google
    Shopping feed, for Meta, TikTok, Snapchat and Google Merchant Center.

    ── WHY IT IS PUBLIC AND UNAUTHENTICATED ────────────────────────────────────────────

    Because it has to be. Every one of the four platforms fetches a feed URL on its own
    schedule from its own infrastructure, and none of them supports anything more than a
    URL (a couple offer HTTP Basic, inconsistently). Gating it would mean it never
    updates.

    What that publishes is the catalogue: names, prices, images and stock states, all of
    which are already on the storefront and in its sitemap. There is no customer data in
    a product feed and no order data — the exposure is a competitor being able to read
    prices they could read anyway by opening the shop.

    Cached for an hour at the edge because the consumers poll it daily at most, and a
    feed rebuild walks every published variant resolving a price per row.

    A plain Django view rather than a DRF one: the response is XML, there is no
    serialisation, no content negotiation and nothing to authenticate, and routing it
    through DRF would only add a renderer that has to be told not to render JSON.
    """
    code = (request.GET.get("country") or "NG").upper()
    country = Country.objects.filter(code=code, is_active=True).select_related("currency").first()
    if country is None:
        # A named market that does not exist is a configuration mistake in somebody's ad
        # account, and an empty 404 says so more usefully than silently serving Nigeria.
        return HttpResponse(
            f"unknown or inactive market: {code}", status=404, content_type="text/plain",
        )
    return HttpResponse(build_feed(country), content_type="application/xml; charset=utf-8")
