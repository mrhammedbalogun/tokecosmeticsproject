"""The BFF shared-secret gate for the two admin endpoints that have exactly one caller.

READ THIS BEFORE CHANGING ANYTHING HERE: it is an ANTI-ABUSE gate, not an authentication
control, and every decision below follows from that. The security controls on
`/auth/admin-token/` are Turnstile, the password, TOTP and the audience claim. A leaked
BFF secret buys an attacker the right to be refused by all four of those, exactly as
before — it buys no access. Nothing in this codebase may describe it as authenticating
the caller, and no future endpoint may rely on it as its only fence.

WHY IT EXISTS. `/auth/admin-token/` and `/admin/staff/invites/accept/` both make an
outbound Turnstile siteverify call before anything else, and both are reachable by
anyone. That cost could not be metered in Django: the admin app calls the API
**server-side**, so every legitimate staff login shares one Vercel egress address with
every attacker, and any volume cap keyed on it is a free staff lockout. (An adversarial
review found precisely that — five empty POSTs per minute locked out every staff member —
which is why both admin throttles count *failed credentials* rather than requests, and
why the volume gap was left open and named in `throttling.py`.)

The observation that closes it is structural rather than statistical: these two endpoints
have exactly ONE legitimate caller in the world, the admin BFF (`admin/src/lib/
admin-session.ts`). An endpoint with a single known server-side caller does not need a
volume cap; it needs proof of coming from that caller. Junk now costs one constant-time
comparison instead of an HTTPS round trip with a five-second timeout.

WHY NOT AN IP ALLOWLIST OF VERCEL'S EGRESS instead: Vercel does not publish a stable
egress range on this plan, the set changes without notice, and a stale entry is a total
staff lockout with no diagnostic. A header the caller controls is both simpler and
rotatable.

UNSET MEANS OFF, exactly like `TURNSTILE_SECRET`. That is the rollout switch — the
backend deploys before the admin app sends the header — and it is the break-glass if the
two ever disagree. See `docs/runbooks/admin-gate.md`.
"""
import hmac
import logging

from django.conf import settings
from rest_framework.exceptions import PermissionDenied

from apps.accounts.turnstile import _DENIED

logger = logging.getLogger("apps.security")

#: The header the admin BFF sends. Mirrored in `admin/src/lib/admin-session.ts`.
HEADER = "X-Admin-BFF-Secret"

#: Django's WSGI spelling of the same header.
_META_KEY = "HTTP_X_ADMIN_BFF_SECRET"


def require_bff_secret(request) -> None:
    """Raise ``PermissionDenied`` unless the request carries the shared secret.

    MUST be called before ``require_turnstile``. That ordering is the whole feature — it
    is what makes junk cheap — and it is asserted directly by
    ``test_the_gate_runs_before_turnstile_so_junk_costs_no_siteverify_call`` rather than
    left to reviewers to notice, because reversing it breaks nothing visible.

    No-op while ``ADMIN_BFF_SECRET`` is unset: the rollout switch, not a bypass.
    """
    expected = settings.ADMIN_BFF_SECRET
    if not expected:
        return

    presented = request.META.get(_META_KEY) or ""
    # `compare_digest` and not `==`: a plain comparison on a secret is a timing oracle,
    # and it is the house rule everywhere else a secret is compared in this app
    # (`totp.py`, `models.py`). Both sides are encoded because compare_digest rejects
    # str inputs containing non-ASCII, which a hostile header can trivially contain.
    if hmac.compare_digest(presented.encode("utf-8", "replace"), expected.encode("utf-8")):
        return

    # ERROR so Sentry raises an event: the response body deliberately cannot say what
    # went wrong, so this line is the operator's only diagnostic. It says "BFF" in as
    # many words because the symptom an operator sees is the Turnstile message.
    #
    # The presented value is NEVER logged — not even truncated. A near-miss is the most
    # interesting thing an attacker could put in a log they might later read, and a
    # wrong secret is frequently somebody's RIGHT secret for another environment.
    logger.error(
        "admin BFF gate refused a request to %s (header %s)",
        request.path,
        "absent" if not presented else "present but wrong",
    )
    # The SAME message Turnstile refuses with, deliberately. A distinct message would
    # advertise that this endpoint wants a secret header, and the first thing an
    # attacker does with that is go looking for the value. The runbook records the
    # operator-facing consequence: "Human verification failed" on EVERY staff login at
    # once means this gate, not Turnstile.
    raise PermissionDenied(_DENIED, code="bff_gate")
