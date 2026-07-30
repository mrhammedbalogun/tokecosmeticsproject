"""DRF exception handler that logs security-relevant rejections, then delegates.

Throttling is the ONLY defence signal several endpoints emit (password reset
deliberately always 200s), so a 429 that isn't logged is an attack that isn't
visible. This wrapper adds the log line and otherwise changes nothing — the
response the client sees is exactly DRF's default.

WHY THE LEVEL IS PER-VIEW. Sentry's logging integration turns ERROR records into
EVENTS and leaves INFO/WARNING as breadcrumbs, so the level is the difference
between "someone is alerted" and "a line exists in a stream nobody is watching".
Those are the right answers for two different populations:

* Customer throttling is routine. Shoppers mistype passwords and refresh carts;
  promoting those 429s would flood Sentry and, by burying it, destroy the signal
  this file exists to raise.
* Reaching the cap on the STAFF gate is the loudest thing that endpoint can
  produce, and it was the one event that never alerted. `AdminLoginView` logs its
  own failures at ERROR, but `Throttled` is raised in `initial()` — before
  `post()` runs — so on a 429 that line never fired and this one logged WARNING.
  The single most interesting rejection was the only silent one.

Hence the opt-in flag rather than a blanket promotion: a view sets
`log_throttling_at_error = True` when its 429s are worth waking someone.
"""
import logging

from rest_framework.exceptions import Throttled
from rest_framework.views import exception_handler as drf_exception_handler

from apps.core.log_safety import scrub

logger = logging.getLogger("apps.security")


def logging_exception_handler(exc, context):
    if isinstance(exc, Throttled):
        request = context.get("request")
        # Scrubbed: this is a caller-supplied string going into a plain-text log
        # line. Django's `str` path converter is `[^/]+`, which matches a newline,
        # so a throttled route with a `<str:>` segment would otherwise let the
        # caller forge whole extra lines into the security log. See
        # apps/core/log_safety.py.
        path = scrub(request.get_full_path()) if request is not None else "?"
        view = context.get("view")
        level = (
            logging.ERROR
            if getattr(view, "log_throttling_at_error", False)
            else logging.WARNING
        )
        logger.log(level, "throttled: %s (retry in %ss)", path, getattr(exc, "wait", None))
    return drf_exception_handler(exc, context)
