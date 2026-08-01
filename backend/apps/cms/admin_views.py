"""CMS administration. `cms.manage` — the scope Plan-16 declared and nothing used.

Until this module existed, `accounts/rbac.py:94` granted `cms.manage` to Owner and
Content, `admin/src/lib/nav.ts` showed a Content editor a "Content" link, and no endpoint
in the project declared the scope. This is the first thing that role can do.
"""
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets
from rest_framework.filters import SearchFilter

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.cms.admin_serializers import (
    BannerAdminSerializer,
    HomepageSectionAdminSerializer,
    MenuItemAdminSerializer,
    PageAdminSerializer,
)
from apps.cms.models import Banner, HomepageSection, MenuItem, Page
from apps.core.audit import AdminAuditMixin


class PageAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """CRUD minus delete, for the reason `Page`'s docstring gives: a slug is a published
    URL that the storefront footer hard-codes and Plan-24's redirects will point at.
    Unpublishing is how a page stops being public; deleting one 404s a live link.

    NOT read-audited: page bodies are marketing copy, not personal data, so this sits with
    the catalogue reads rather than the order desk (`apps/core/audit.py` draws that line).
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("cms.manage")]
    serializer_class = PageAdminSerializer
    audit_serializers = (PageAdminSerializer,)
    audit_model_label = "cms.page"
    queryset = Page.objects.all()
    lookup_field = "slug"
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["status"]
    search_fields = ["title", "slug"]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]


class BannerAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """`marketing.manage` — see `rbac.py`: a banner announces a promotion, so it is
    campaign material rather than the legally load-bearing pages `cms.manage` protects.

    DELETE IS ALLOWED here, unlike pages and bank accounts. A banner addresses no URL and
    nothing links to it; a finished campaign's artwork is genuinely disposable, and
    forcing a growing list of dead banners on a marketer would make the live ones harder
    to find — which is its own kind of risk.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("marketing.manage")]
    serializer_class = BannerAdminSerializer
    audit_serializers = (BannerAdminSerializer,)
    audit_model_label = "cms.banner"
    queryset = Banner.objects.prefetch_related("countries").all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["placement", "is_active"]


class HomepageSectionAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """The homepage's running order. `marketing.manage`: the homepage IS the campaign."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("marketing.manage")]
    serializer_class = HomepageSectionAdminSerializer
    audit_serializers = (HomepageSectionAdminSerializer,)
    audit_model_label = "cms.homepagesection"
    queryset = HomepageSection.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["type", "is_active"]


class MenuItemAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """`cms.manage`: navigation is site structure, and the footer's policy links are the
    content that scope exists to protect."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("cms.manage")]
    serializer_class = MenuItemAdminSerializer
    audit_serializers = (MenuItemAdminSerializer,)
    audit_model_label = "cms.menuitem"
    queryset = MenuItem.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["menu", "is_active"]
