from django.contrib import admin

from apps.newsletter.models import NewsletterSubscriber


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "source", "consented_at", "unsubscribed_at")
    list_filter = ("source",)
    search_fields = ("email",)
