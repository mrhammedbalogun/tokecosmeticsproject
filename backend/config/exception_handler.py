"""DRF exception handler that logs security-relevant rejections, then delegates.

Throttling is the ONLY defence signal several endpoints emit (password reset
deliberately always 200s), so a 429 that isn't logged is an attack that isn't
visible. This wrapper adds the log line and otherwise changes nothing — the
response the client sees is exactly DRF's default.
"""
import logging

from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("apps.security")


def logging_exception_handler(exc, context):
    if isinstance(exc, Throttled):
        request = context.get("request")
        path = request.get_full_path() if request is not None else "?"
        logger.warning(
            "throttled: %s (retry in %ss)", path, getattr(exc, "wait", None),
        )
    return drf_exception_handler(exc, context)
