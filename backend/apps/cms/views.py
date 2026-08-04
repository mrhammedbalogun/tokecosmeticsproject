"""Public CMS endpoints — unauthenticated, cached by the storefront."""
from rest_framework import generics
from rest_framework.permissions import AllowAny

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cms.models import Banner, HomepageSection, MenuItem, Page
from apps.cms.serializers import (
    PublicBannerSerializer,
    PublicGoogleReviewSerializer,
    PublicHomepageSectionSerializer,
    PublicMenuItemSerializer,
    PublicPageSerializer,
)


class PublicPageDetailView(generics.RetrieveAPIView):
    """`GET /api/v1/cms/pages/{slug}/`.

    PUBLISHED ONLY, and a draft is a 404 rather than a 403: the existence of an unpublished
    page is not public information, and the storefront's job with either answer is the same.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    serializer_class = PublicPageSerializer
    lookup_field = "slug"
    queryset = Page.objects.filter(status=Page.PUBLISHED)


class PublicPageListView(generics.ListAPIView):
    """`GET /api/v1/cms/pages/` — slugs and titles only, for `sitemap.ts`.

    Deliberately not paginated: there are eleven of these and a sitemap wants all of them.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []
    serializer_class = PublicPageSerializer
    pagination_class = None
    queryset = Page.objects.filter(status=Page.PUBLISHED)


class PublicHomepageView(APIView):
    """`GET /api/v1/cms/homepage/` — the ordered sections plus the banners that are live
    right now.

    ONE REQUEST, not three. The homepage is the most-hit page on the site and every extra
    round trip to the VPS is paid on a Nigerian mobile connection.

    SCHEDULING IS APPLIED HERE, not in the client: a banner outside its window must never
    reach the browser, or "scheduled" would mean "hidden by CSS" and a campaign would leak
    early to anyone reading the payload.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        now = timezone.now()
        country = (request.headers.get("X-Country") or "").upper()

        banners = Banner.objects.filter(is_active=True).prefetch_related("countries")
        live = [b for b in banners if b.is_live(now)]
        if country:
            # An empty country list means EVERYWHERE, matching `Product.available_countries`.
            live = [
                b for b in live
                if not b.countries.exists()
                or country in {c.code for c in b.countries.all()}
            ]

        sections = HomepageSection.objects.filter(is_active=True)
        # Landing redesign: the reviews ride the same single request, for the same
        # round-trip reason. Meta may not exist yet; the storefront hides the section
        # when there are no reviews, so an empty shape is a valid answer.
        from apps.cms.models import GoogleReview, GoogleReviewsMeta

        meta = GoogleReviewsMeta.objects.first()
        return Response({
            "sections": PublicHomepageSectionSerializer(sections, many=True).data,
            "banners": PublicBannerSerializer(live, many=True, context={"request": request}).data,
            "reviews": {
                "rating": str(meta.rating) if meta else None,
                "count_text": meta.review_count_text if meta else "",
                "profile_url": meta.profile_url if meta else "",
                "items": PublicGoogleReviewSerializer(
                    GoogleReview.objects.filter(is_active=True), many=True
                ).data,
            },
        })


class PublicMenuView(APIView):
    """`GET /api/v1/cms/menus/` — header and footer links, grouped."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        items = MenuItem.objects.filter(is_active=True)
        data = PublicMenuItemSerializer(items, many=True).data
        return Response({
            "header": [i for i in data if i["menu"] == "header"],
            "footer": [i for i in data if i["menu"] == "footer"],
        })
