"""Auth security events → the ``apps.security`` log stream.

``user_login_failed`` fires from ``django.contrib.auth.authenticate()``, which
SimpleJWT's token serializer calls — so JWT logins are covered without touching
the serializer. (``user_logged_in`` does NOT fire for JWT flows — it belongs to
session ``login()`` — so the success line lives in LoginView instead.)

The email is logged in the clear on purpose: these are the store's own ops logs,
and "which account is being attacked" is the entire point of the line. Sentry is
configured with send_default_pii=False, so these lines surface there only as
breadcrumb text on real errors, not as indexed user identities.
"""
import logging

from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver

logger = logging.getLogger("apps.security")


@receiver(user_login_failed)
def log_login_failed(sender, credentials, request, **kwargs):
    email = (credentials or {}).get("email", "<no email>")
    logger.warning("login failed for %s", email)
