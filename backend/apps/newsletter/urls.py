from django.urls import path

from apps.newsletter.views import SubscribeView, UnsubscribeView

urlpatterns = [
    path("newsletter/", SubscribeView.as_view(), name="newsletter-subscribe"),
    path("newsletter/unsubscribe/", UnsubscribeView.as_view(), name="newsletter-unsubscribe"),
]
