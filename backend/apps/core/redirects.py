"""Legacy URL redirects (Plan-24) — the public resolver and the admin surface.

`core.Redirect` has existed since Plan-03 and until now nothing read it. This is what
reads it.

── WHAT THE STOREFRONT DOES WITH THIS ───────────────────────────────────────────────────

The storefront's ROOT CATCH-ALL (`storefront/src/app/[...slug]/page.tsx`) calls
`/api/v1/meta/redirect/?path=…` and, on a hit, issues the redirect. A catch-all is reached
only when no real route matched, which is the whole design: WordPress served pages, posts
and help articles from the root, and three of those slugs are live storefront routes
today — `/account` was a help article, `/search` and `/checkout` were pages. A resolver
consulted BEFORE routing would send a signed-in customer from their own account page to an
article about accounts. Here the App Router ranks every real route above the catch-all, so
the precedence is a property of the framework rather than a skip-list somebody has to
remember to update.

── PATH NORMALISATION IS SHARED, NOT DUPLICATED ─────────────────────────────────────────

WordPress permalinks all end in `/`; none of the new ones do. `normalise_path` is used by
BOTH the seeder and the resolver, so a row written one way cannot fail to match a request
made the other way. Storing both forms was the alternative and would give two rows that
can disagree.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db.models import F
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import serializers, viewsets
from rest_framework.filters import SearchFilter
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.core.models import Redirect

logger = logging.getLogger(__name__)

#: Long, because this table changes at migration time and essentially never after.
#: Invalidated by a version bump on any admin write, the same shape the catalogue uses.
CACHE_SECONDS = 60 * 60
_VERSION_KEY = "redirects:version"


def _version() -> int:
    return cache.get_or_set(_VERSION_KEY, 1, None) or 1


def bump_version() -> None:
    """Called on every admin write. A redirect that keeps pointing at the old target for
    an hour after somebody fixed it is exactly the sort of thing that gets debugged twice."""
    try:
        cache.incr(_VERSION_KEY)
    except ValueError:
        cache.set(_VERSION_KEY, 1, None)


def normalise_path(path: str) -> str:
    """The one definition of "the same URL", used by the seeder AND the resolver.

    Lowercased, query and fragment dropped, leading slash forced, trailing slash removed.
    `/Our-Story/?utm_source=x` and `/our-story` are the same row. Root stays `/`.

    Lowercasing is safe here because every slug WordPress generated is already lowercase;
    it exists to catch hand-typed and mis-cased inbound links, which is most of what a
    redirect table is for.
    """
    path = (path or "").strip()
    for sep in ("?", "#"):
        path = path.split(sep, 1)[0]
    path = path.lower()
    if not path.startswith("/"):
        path = "/" + path
    path = path.rstrip("/")
    return path or "/"


def resolve(path: str) -> Redirect | None:
    """The cached lookup. Returns None for a genuine 404."""
    key = f"redirect:{_version()}:{normalise_path(path)}"
    cached = cache.get(key)
    if cached is not None:
        # `False` is the cached "no such redirect" — without it every 404 on the site is a
        # database query, and 404 traffic is exactly what bots generate most of.
        return None if cached is False else cached

    row = Redirect.objects.filter(old_path=normalise_path(path)).first()
    cache.set(key, row or False, CACHE_SECONDS)
    return row


def count_hit(row: Redirect) -> None:
    """Best-effort. A redirect must never fail because a counter did.

    `hits` exists to show which old URLs still receive traffic — worth knowing for a year,
    noise after that. An F() update avoids a read-modify-write race between workers, and
    the bare except is deliberate: a redirect that 500s because the counter failed is
    strictly worse than one that under-counts.
    """
    try:
        Redirect.objects.filter(pk=row.pk).update(hits=F("hits") + 1)
    except Exception:  # noqa: BLE001 — see docstring
        logger.warning("redirect hit counter failed for %s", row.old_path, exc_info=True)


class PublicRedirectView(APIView):
    """GET /api/v1/meta/redirect/?path=/our-story/

    Public and unauthenticated, because it answers questions about public URLs and is
    called for anonymous visitors arriving from Google. It reveals only what a crawler
    could learn by requesting the old URL itself.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        path = request.query_params.get("path", "")
        row = resolve(path)
        if row is None:
            return Response({"detail": "No redirect for that path."}, status=404)
        count_hit(row)
        return Response(
            {
                "old_path": row.old_path,
                "new_path": row.new_path,
                "status_code": row.status_code,
            }
        )


class RedirectAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Redirect
        fields = ["id", "old_path", "new_path", "status_code", "hits", "created_at"]
        read_only_fields = ["id", "hits", "created_at"]

    def validate_old_path(self, value):
        return normalise_path(value)

    def validate_status_code(self, value):
        # 301 permanent (the migration default), 302 temporary, 410 Gone for content that
        # has no successor. Anything else in this column is a typo that would render as a
        # broken response to a real visitor.
        if value not in (301, 302, 410):
            raise serializers.ValidationError("Must be 301, 302 or 410.")
        return value

    def validate(self, attrs):
        old = attrs.get("old_path", getattr(self.instance, "old_path", ""))
        new = attrs.get("new_path", getattr(self.instance, "new_path", ""))
        status_code = attrs.get("status_code", getattr(self.instance, "status_code", 301))
        if status_code != 410 and normalise_path(new) == old:
            # A row pointing at itself is an infinite redirect the browser breaks, not the
            # server — so nothing here would ever log it.
            raise serializers.ValidationError("A redirect cannot point at itself.")
        return attrs


class RedirectAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    """Full CRUD including DELETE, under `cms.manage`.

    Delete IS offered here, unlike `PageAdminViewSet`. The reasoning inverts: deleting a
    CMS page 404s a live link, whereas deleting a redirect row only stops a *legacy* URL
    being forwarded — the destination is untouched. A wrong redirect is more harmful than
    a missing one, so removing it must be possible without a database console.
    """

    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("cms.manage")]
    serializer_class = RedirectAdminSerializer
    audit_serializers = (RedirectAdminSerializer,)
    audit_model_label = "core.redirect"
    queryset = Redirect.objects.all().order_by("old_path")
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ["status_code"]
    search_fields = ["old_path", "new_path"]

    def perform_create(self, serializer):
        super().perform_create(serializer)
        bump_version()

    def perform_update(self, serializer):
        super().perform_update(serializer)
        bump_version()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        bump_version()
