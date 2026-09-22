from rest_framework.routers import SimpleRouter

from apps.careers.admin_views import JobApplicationAdminViewSet, JobPostingAdminViewSet
from apps.careers.notification_views import CareersNotificationAdminViewSet

router = SimpleRouter()
router.register("careers/jobs", JobPostingAdminViewSet, basename="admin-career-job")
router.register(
    "careers/applications", JobApplicationAdminViewSet, basename="admin-career-application"
)
# The screen's counts live at `careers/applications/stats/`, an @action on the viewset
# above rather than a view of its own — see its docstring for why the audit guard is the
# reason.

router.register(
    # Who gets emailed when somebody applies. Its own scope and its own viewset — see
    # `notification_views.py` for why the event is pinned three ways.
    "careers/notifications",
    CareersNotificationAdminViewSet,
    basename="admin-career-notification",
)

urlpatterns = router.urls
