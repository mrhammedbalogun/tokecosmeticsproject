"""Store-directory admin (Plan-42).

SCOPE: `products.manage` — Owner and Manager. The precedent is exact: pickup
locations (`delivery/admin_views.SenderLocationAdminViewSet`) are also rows about
physical shops, also maintained by whoever runs the day to day, and also filed
under this scope rather than under `marketing.manage`. The reviewing model argued
for `marketing.manage` on the grounds that a distributor listing is brand presence
rather than catalogue; the two grants are the same pair of roles today, so the
argument is about naming, and matching the nearest existing surface wins.

DELETE ARCHIVES. It does not remove the row. See the model docstring for why —
short version: nothing references a store so a purge would be safe, but these are
hand-collected field records and safe-to-delete is not worth-deleting. `restore`
undoes it. There is deliberately no purge endpoint at all; a genuinely bogus row
lives out its life archived and out of sight.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.authentication import AdminJWTAuthentication
from apps.accounts.rbac import HasAdminScope
from apps.core.audit import AdminAuditMixin
from apps.stores.admin_serializers import StoreLocationAdminSerializer
from apps.stores.filters import StoreLocationFilter
from apps.stores.models import StoreLocation


class StoreLocationAdminViewSet(AdminAuditMixin, viewsets.ModelViewSet):
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [HasAdminScope("products.manage")]
    serializer_class = StoreLocationAdminSerializer
    audit_serializers = (StoreLocationAdminSerializer,)
    filter_backends = [DjangoFilterBackend]
    filterset_class = StoreLocationFilter
    # PAGINATED, unlike the operator-scale lists elsewhere in this codebase. A
    # distributor network is the one table here that is expected to reach the
    # hundreds, and the brief says so out loud: "Do not assume there will only ever
    # be a few stores."
    queryset = (
        StoreLocation.objects.select_related("country", "state_region", "area_region")
        .order_by("name", "id")
    )
    # `id` is the tie-break on purpose: PageNumberPagination over a non-unique sort
    # key silently repeats and skips rows across page boundaries, which on a
    # directory reads as "we lost a distributor".

    def get_queryset(self):
        """Archived rows are out of sight unless asked for.

        LIST ONLY. The default view of a directory is the directory (`?status=archived`
        and `?status=all` reach the rest, via the FilterSet — this supplies only the
        default, which a FilterSet cannot express). Applying it to detail routes too
        would make `restore` unable to find the very rows it exists to restore.
        """
        queryset = super().get_queryset()
        if self.action == "list" and not self.request.query_params.get("status"):
            queryset = queryset.filter(archived_at__isnull=True)
        return queryset

    def create(self, request, *args, **kwargs):
        """Turn the race the unique index catches into the same 409 the soft
        warning uses.

        Two operators saving the same shop in the same second both pass
        `possible_duplicates` (neither row exists yet) and the second one hits the
        database constraint. Untranslated that is a 500 and a Sentry event about
        nothing; here it is the answer the UI already knows how to render.

        THE INNER `atomic()` IS LOAD-BEARING, not decoration. `AdminAuditMixin.dispatch`
        already opened a transaction around this request; an IntegrityError inside it
        poisons that transaction, and every later query — including rendering this very
        response — then raises `TransactionManagementError`. The savepoint confines the
        rollback to the failed INSERT.
        """
        try:
            with transaction.atomic():
                return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"detail": "That store was just added by someone else.",
                 "possible_duplicates": []},
                status=status.HTTP_409_CONFLICT,
            )

    def update(self, request, *args, **kwargs):
        try:
            with transaction.atomic():
                return super().update(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"detail": "Those details now match another store on file.",
                 "possible_duplicates": []},
                status=status.HTTP_409_CONFLICT,
            )

    def destroy(self, request, *args, **kwargs):
        """Archive, do not delete. 204 either way, so the client needs no special case.

        Snapshotted into the audit row first: `changes` is normally built from the
        request body, which a DELETE has none of, so without this the trail would
        prove only that *something* was archived.
        """
        store = self.get_object()
        self._archived = {"id": store.pk, "name": store.name, "address": store.address}
        if store.archived_at is None:
            store.archived_at = timezone.now()
            store.is_active = False
            store.save(update_fields=["archived_at", "is_active", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _changes(self, response) -> dict:
        changes = super()._changes(response)
        if self.request.method.upper() == "DELETE" and hasattr(self, "_archived"):
            changes["archived"] = self._archived
        return changes

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        """Bring an archived store back, INACTIVE.

        Deliberately not straight back onto the website: the row was archived for a
        reason, and whoever restores it should confirm the address and phone before
        customers are sent there. One more click, and it is the click that stops a
        closed shop reappearing with a year-old phone number.

        The unique index can refuse this — somebody may have re-typed the shop after
        it was archived — so the collision is caught and reported rather than 500ing.
        """
        store = self.get_object()
        if store.archived_at is None:
            return Response({"detail": "That store is not archived."},
                            status=status.HTTP_400_BAD_REQUEST)
        store.archived_at = None
        store.is_active = False
        try:
            # Savepoint for the same reason as `create` above — see that docstring.
            with transaction.atomic():
                store.save(update_fields=["archived_at", "is_active", "updated_at"])
        except IntegrityError:
            return Response(
                {"detail": "This store was added again while it was archived. "
                           "Edit or archive that one first.",
                 "possible_duplicates": []},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(self.get_serializer(store).data)
