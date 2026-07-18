from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class NewsletterSubscriber(TimeStampedModel):
    """A marketing-list membership. Capture only (Plan-11); campaign sending is Plan-30.
    Re-subscribing after an unsubscribe clears unsubscribed_at rather than duplicating."""

    email = models.EmailField(unique=True)
    source = models.CharField(max_length=40, blank=True)  # "footer", "checkout", ...
    consented_at = models.DateTimeField(default=timezone.now)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        state = "unsubscribed" if self.unsubscribed_at else "active"
        return f"{self.email} ({state})"
