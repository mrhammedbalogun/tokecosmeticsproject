"""Public programme routes. Both anonymous; see `views` for where the abuse controls sit.

NO OBJECT-ADDRESSED ROUTE EXISTS HERE, and that is worth stating rather than noticing:
there is one programme, so the apply endpoint needs no identifier in its path, and
nothing about an existing application can be read back through this surface at all.
That is why `apps/core/tests/test_object_ownership.py` has no entry for this app.
"""
from django.urls import path

from apps.entrepreneurship.views import ApplyView, ProgramConfigView

urlpatterns = [
    path("config/", ProgramConfigView.as_view(), name="programme-config"),
    path("apply/", ApplyView.as_view(), name="programme-apply"),
]
