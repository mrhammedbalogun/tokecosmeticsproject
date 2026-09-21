from rest_framework.routers import SimpleRouter

from apps.careers.admin_views import JobApplicationAdminViewSet, JobPostingAdminViewSet

router = SimpleRouter()
router.register("careers/jobs", JobPostingAdminViewSet, basename="admin-career-job")
router.register(
    "careers/applications", JobApplicationAdminViewSet, basename="admin-career-application"
)
# The screen's counts live at `careers/applications/stats/`, an @action on the viewset
# above rather than a view of its own — see its docstring for why the audit guard is the
# reason.

urlpatterns = router.urls
