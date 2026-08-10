"""CMS administration. `cms.manage` — the scope Plan-16 declared and nothing used.

Until this module existed, `accounts/rbac.py:94` granted `cms.manage` to Owner and
Content, `admin/src/lib/nav.ts` showed a Content editor a "Content" link, and no endpoint
in the project declared the scope. This is the first thing that role can do.
"""
from botocore.exceptions import ClientError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.filters import SearchFilter

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.cms import admin_serializers, s3_uploads
from apps.cms.admin_serializers import (
    GoogleReviewAdminSerializer,
    GoogleReviewsMetaAdminSerializer,
    BannerAdminSerializer,
    HomepageSectionAdminSerializer,
    MediaAssetAdminSerializer,
    MenuItemAdminSerializer,
    PageAdminSerializer,
    VideoFinalizeSerializer,
    VideoTicketRequestSerializer,
)
from apps.cms.video_sniff import VIDEO_CONTENT_TYPES, is_faststart, sniff_video_container
from apps.cms.models import (
    Banner, HomepageSection, MediaAsset, MenuItem, Page, GoogleReview, GoogleReviewsMeta,
)
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


class MediaAssetAdminViewSet(
    AdminAuditMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """The media library: list, search, upload. See `MediaAsset` for why no delete.

    `marketing.manage`, like the banners the library feeds — today its only consumer.
    When product images join, this needs an OR of scopes; that is deliberately NOT
    `HasAdminScope(...) | HasAdminScope(...)` yet, because the surface guard
    (`test_admin_surface_guard.py`) reads a single `.scope` off each permission and the
    OR story should be built there first, not smuggled past it. The two scopes' holders
    are identical today (Owner + Manager), so nothing is lost by waiting.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("marketing.manage")]
    serializer_class = MediaAssetAdminSerializer
    audit_serializers = (
        MediaAssetAdminSerializer, VideoTicketRequestSerializer, VideoFinalizeSerializer,
    )
    audit_model_label = "cms.mediaasset"
    queryset = MediaAsset.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["kind"]
    search_fields = ["original_name", "file"]

    @action(detail=False, methods=["post"], url_path="video-ticket")
    def video_ticket(self, request):
        """Mint a one-shot S3 POST form. The bytes bypass this server entirely.

        WHY THIS EXISTS: Vercel rejects function request bodies over ~4.5MB at its edge
        before Next runs (measured 2026-08-09: 3.91MB passes, 4.30MB 413s), so a video
        relayed through the admin's server actions cannot arrive. Images still take the
        old path — they are downscaled under 4MB in the browser and their full-byte
        Pillow check is worth keeping.
        """
        body = VideoTicketRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        key = s3_uploads.new_incoming_key(body.validated_data["container"])
        ticket = s3_uploads.mint_video_post(
            key, max_bytes=admin_serializers.MAX_VIDEO_BYTES,
        )
        return Response({"url": ticket["url"], "fields": ticket["fields"], "key": key})

    @action(detail=False, methods=["post"], url_path="video-finalize")
    def video_finalize(self, request):
        """Verify what landed, publish it, and record the asset.

        Order matters: copy BEFORE the row is written. The inverse would leave a row
        pointing at nothing, which a banner could then attach to.
        """
        body = VideoFinalizeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        key = body.validated_data["key"]

        try:
            s3_uploads.assert_incoming(key)
        except s3_uploads.UnsafeKeyError:
            raise serializers.ValidationError({"key": "That upload key is not valid."}) from None

        try:
            size, etag = s3_uploads.head_incoming(key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey"):
                raise
            # A retry of a finalize that already succeeded: the quarantine copy was
            # cleaned up, but the published asset exists. Answer as if nothing happened
            # twice — that is what makes double-clicking Save harmless.
            existing = MediaAsset.objects.filter(file=s3_uploads.library_key_for(key)).first()
            if existing is not None:
                return Response(MediaAssetAdminSerializer(existing).data, status=200)
            raise serializers.ValidationError(
                {"key": "That upload has expired or was never completed. Choose the "
                        "file again."}
            ) from None

        # Read the cap off the module, not a from-import: the "ticket lied" test shrinks
        # it at runtime to prove this re-check is real.
        max_bytes = admin_serializers.MAX_VIDEO_BYTES
        if size > max_bytes:
            s3_uploads.discard_incoming(key)
            raise serializers.ValidationError(
                {"key": f"That video is {size // (1024 * 1024)} MB — the limit is "
                        f"{max_bytes // (1024 * 1024)} MB."}
            )

        head = s3_uploads.read_incoming_head(key)
        container = sniff_video_container(head)
        if container is None:
            s3_uploads.discard_incoming(key)
            raise serializers.ValidationError(
                {"key": "That file isn't an mp4 or webm video."}
            )

        dest = s3_uploads.publish_incoming(
            key, etag=etag, content_type=VIDEO_CONTENT_TYPES[container],
        )
        asset, created = MediaAsset.objects.get_or_create(
            file=dest,
            defaults={
                "kind": MediaAsset.VIDEO,
                "original_name": body.validated_data["original_name"][:255],
                "size": size,
                "uploaded_by": request.user,
            },
        )
        s3_uploads.discard_incoming(key)

        payload = MediaAssetAdminSerializer(asset).data
        if not is_faststart(head):
            payload["warning"] = (
                "This video is not faststart-encoded, so browsers must download all of "
                "it before playing. Re-encode with ffmpeg's -movflags +faststart."
            )
        return Response(payload, status=201 if created else 200)


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


class GoogleReviewAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """`marketing.manage`, like banners: featured reviews are campaign material.
    DELETE allowed for the banner's reason — a retired review is disposable."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("marketing.manage")]
    serializer_class = GoogleReviewAdminSerializer
    audit_serializers = (GoogleReviewAdminSerializer,)
    audit_model_label = "cms.googlereview"
    queryset = GoogleReview.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["is_active"]


class GoogleReviewsMetaAdminView(AdminAuditMixin, APIView):
    """GET/PUT the singleton header numbers (rating, count text, profile URL)."""

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("marketing.manage")]
    audit_action = "google_reviews_meta"
    audit_model_label = "cms.googlereviewsmeta"

    def get(self, request):
        meta = GoogleReviewsMeta.objects.first()
        if meta is None:
            return Response({"rating": None, "review_count_text": "", "profile_url": ""})
        return Response(GoogleReviewsMetaAdminSerializer(meta).data)

    def put(self, request):
        meta = GoogleReviewsMeta.objects.first() or GoogleReviewsMeta()
        serializer = GoogleReviewsMetaAdminSerializer(meta, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
