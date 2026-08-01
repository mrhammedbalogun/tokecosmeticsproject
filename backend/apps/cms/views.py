"""Public CMS endpoints — unauthenticated, cached by the storefront."""
from rest_framework import generics
from rest_framework.permissions import AllowAny

from apps.cms.models import Page
from apps.cms.serializers import PublicPageSerializer


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
