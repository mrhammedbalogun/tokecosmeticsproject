"""The camera on the admin surface: one row per staff action, written by a DRF mixin.

Plan-16 Tasks 1-3b built a FENCE — an audience claim, scopes, mandatory TOTP — and
their tests prove an outsider cannot get in. This module is the CAMERA, and it is
pointed at a different person: the one who is already inside with a key. An insider,
or an attacker holding a stolen staff session. Every decision below follows from that,
and the question worth re-asking whenever this file is edited is the adversarial one:
**which staff action could I take that leaves no row?**

── WHY THE WRITE IS IN THE SAME TRANSACTION AS THE MUTATION ────────────────────────

`AdminAuditMixin.dispatch` opens `transaction.atomic()` around the whole request and
writes the row inside it. If the audit insert fails, the mutation rolls back with it —
both or neither.

That is the right failure direction for an ADMIN surface specifically. On a customer
surface, refusing to take an order because a log line failed would be absurd; here,
"the refund went through and nothing recorded it" is the exact state this table exists
to make impossible. It costs nothing, because it is the same database and the same
transaction — no second system to be up.

There is deliberately NO Celery path. A queued audit write re-introduces exactly the
problem same-transaction solves: the mutation commits, the queue drops the message (or
the broker is down, or the worker OOMs), and the row never appears — with the added
cruelty that everything looks fine. `test_audit.py::
test_a_failing_audit_insert_rolls_the_mutation_back` drives the failure.

Note that production already sets `ATOMIC_REQUESTS = True`, so in prod this atomic is
a savepoint inside the request transaction and the guarantee holds either way. The
explicit block is what makes it hold in dev, in tests, and on the day somebody turns
`ATOMIC_REQUESTS` off.

── WHY READS ARE AUDITED, ON PII ENDPOINTS ONLY ────────────────────────────────────

Design ruling 4 of the plan said "reads are not audited (volume, no value)". That was
imported from customer-facing intuition and it is wrong here. This surface has a staff
population countable on one hand and a read volume of essentially nothing, and
"Support bulk-exported the customer list" is not an edge case — it is the CANONICAL
insider event an audit log exists for. A log that records every price edit and no
exports would miss the only exfiltration this store can suffer.

So: every list and every customer/order detail GET writes a row carrying the query
parameters (the filters and search terms are the interesting part — they say what was
being hunted for) and either the object id or the result count. **Never the response
payload**: storing the exported rows would put a second copy of the customer list in
the very table an attacker is already reading.

Non-PII reads — catalogue, CMS, dashboards — stay unaudited. `audit_reads` is the
opt-in flag, and `test_audit_guard.py` asserts that every view carrying an `orders.*`
or `customers.*` scope AND a GET route sets it, so a future customers endpoint is
caught the day it is routed rather than the day somebody remembers.

── WHY `changes` IS AN ALLOWLIST ───────────────────────────────────────────────────

The whole answer to "what stops a field called `api_secret` landing in this table" is
that unlisted keys are never stored. Nothing stops such a key ARRIVING — the request
body is whatever the caller sent — but the row only ever contains keys somebody wrote
down. A scrub-by-name denylist (`password`, `secret`, `token`, …) was refused: it is a
fictional control, it fails on the first field nobody thought of, and its presence
would make the next reader believe the table is safe by construction when it is safe
only by vigilance.

The seatbelt that keeps the allowlist honest is `test_audit_guard.py::
test_no_allowlisted_key_is_a_write_only_serializer_field`. Write-only fields are
exactly the ones that exist to be submitted and never returned — passwords first among
them — so an allowlist entry naming one is the single most likely way a secret gets in
here, and it is now a test failure rather than a code review.

`changes` is built from **`request.data`**, filtered by the allowlist, rather than from
`serializer.validated_data`. Two reasons, and one honest cost. It works uniformly for
the eleven admin views that parse their body with an inline serializer or with no
serializer at all, so there is one code path rather than a per-view hook that some view
will eventually not have; and `validated_data` holds coerced Python objects (model
instances, `Decimal`, uploaded files) that are not JSON and would need a second
serialisation pass with its own escaping questions. The cost is that a row records what
was SUBMITTED, not what was saved — a key the serializer ignored still appears. That is
stated on the API and is the safe direction to be wrong in for an audit trail.

Values go in as structured JSON, which is also what makes newline forgery a non-issue
for the database row (the `apps.security` mirror carries no values at all, so it is not
an issue there either — see `record_audit`).
"""
from __future__ import annotations

import json
import logging

from django.db import transaction
from django.db.models import Q, TextField
from django.db.models.functions import Cast

from apps.core.log_safety import scrub

security_logger = logging.getLogger("apps.security")

# The tombstone left behind when a deleted customer's PII is redacted out of a row.
# A marker rather than an empty string so that "this value was removed under a deletion
# request" and "this field was submitted blank" stay distinguishable forever.
REDACTED = "[redacted: account deleted]"

# Per-row cap on the serialised `changes` JSON. An unbounded JSONField fed straight
# from request bodies is a disk-DoS lever: an authorised-but-hostile staff member (or a
# stolen session) can PATCH a product with a 50MB `description` as fast as the network
# allows and each attempt is durably stored. 8KB is far more than any real admin edit —
# the largest legitimate one in this codebase is a product description — and small
# enough that a million rows is gigabytes rather than terabytes.
MAX_CHANGES_BYTES = 8192

# Per-VALUE cap, applied before the per-row one. Without it a single 8KB-1 value fills
# the row's whole budget and truncates everything else away, so the interesting keys
# (which field was touched) lose to the boring one.
MAX_VALUE_CHARS = 512

_TRUNCATED_VALUE = "…[truncated]"


def _jsonable(value, depth: int = 0):
    """Coerce an arbitrary request-body value into something `JSONField` can store.

    Request bodies arrive parsed from JSON, so most values are already fine — but a
    multipart request puts `UploadedFile` objects in `request.data`, and a caller can
    nest arbitrarily deeply. Anything that is not a JSON primitive becomes its `str()`,
    which for a file is its filename: useful, bounded, and never the file's contents.

    `depth` caps recursion. A body nested 200 levels deep would otherwise blow the
    stack inside the audit write — which, given the same-transaction rule above, would
    turn a malformed request into a rolled-back mutation rather than a 400.
    """
    if depth >= 6:
        return _TRUNCATED_VALUE
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= MAX_VALUE_CHARS else value[:MAX_VALUE_CHARS] + _TRUNCATED_VALUE
    if isinstance(value, (list, tuple)):
        return [_jsonable(item, depth + 1) for item in value[:50]]
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth + 1) for k, v in list(value.items())[:50]}
    return _jsonable(str(value), depth + 1)


def build_changes(data, allowlist) -> dict:
    """The allowlisted subset of a request body, JSON-safe and size-capped.

    Returns `{}` for an empty allowlist, which is the correct answer for the endpoints
    that take no body worth recording (a CSV import, an invite revoke): the ROW still
    gets written — action, actor, object, time — and only the field-level detail is
    absent. "No changes recorded" and "no row" are very different things, and only the
    second one is a hole.
    """
    if not allowlist or not hasattr(data, "get"):
        return {}
    changes = {key: _jsonable(data.get(key)) for key in allowlist if key in data}
    if len(json.dumps(changes, default=str).encode()) <= MAX_CHANGES_BYTES:
        return changes
    # Explicit marker, keys kept. A silently truncated row reads as a complete one, and
    # somebody will later conclude the staff member only edited two fields.
    return {
        "__truncated__": True,
        "__keys__": sorted(changes),
        "__reason__": f"changes exceeded {MAX_CHANGES_BYTES} bytes",
    }


def record_audit(
    *,
    actor=None,
    actor_email: str = "",
    token_jti: str = "",
    client_ip: str = "",
    model_label: str = "",
    object_id: str = "",
    action: str,
    changes: dict | None = None,
):
    """Write one row and mirror it to `apps.security`. The only place a row is created.

    THE MIRROR CARRIES KEYS AND IDS, NEVER VALUES, and that single rule buys three
    things at once. The database stops being the only copy of the trail, so an attacker
    who can rewrite `changes` (see the model docstring — the trigger permits exactly
    that one column) has not erased the fact that the action happened. Customer PII
    stays out of the log stream and therefore out of Sentry breadcrumbs, for free.  And
    because no caller-supplied VALUE is interpolated, the log-injection lesson from
    `apps/core/log_safety.py` cannot bite here — the ids that are interpolated are
    scrubbed anyway, because an order number comes out of a URL and a URL comes from
    the caller.

    INFO, not ERROR. Every one of these lines is an authorised, deliberate act by
    somebody who completed the full admin ceremony; at ERROR they would become Sentry
    events and the genuine admin alerts (failed logins, recovery-code use) would drown
    in them within a day. Sentry keeps INFO as breadcrumbs on whatever error does fire,
    which is exactly the context worth having.
    """
    from apps.core.models import AuditLog

    changes = changes or {}
    row = AuditLog.objects.create(
        actor=actor,
        actor_email=actor_email,
        token_jti=token_jti,
        client_ip=client_ip,
        model_label=model_label,
        object_id=object_id,
        action=action,
        changes=changes,
    )
    security_logger.info(
        "audit %s %s %s by %s jti=%s ip=%s keys=%s",
        scrub(action),
        scrub(model_label),
        scrub(object_id),
        scrub(actor_email),
        scrub(token_jti),
        scrub(client_ip),
        scrub(",".join(sorted(str(k) for k in changes))),
    )
    return row


def redact_audit_values(*, model_labels_and_ids, email: str = "") -> int:
    """Hollow out the VALUES in `changes` for rows about a deleted customer.

    Called by `apps.accounts.tasks.anonymize_deleted_accounts`, which is the second
    phase of soft account deletion. THE ROW SURVIVES, THE VALUES DO NOT: keys, object
    id, actor, actor email, IP, jti and timestamp all stay. Both promises then hold at
    once — the deletion promise ("your data is gone", and the values are) and the audit
    promise ("staff member X edited customer 123's address at 14:02", still provable,
    just without the address).

    Rows are found two ways, because one is not enough:

    * by `(model_label, object_id)` — every row naming the user or one of their orders;
    * by a text match on `changes` for the user's pre-deletion email — which catches
      the read-audit rows recording an admin's SEARCH for that address, whose object id
      is empty because a list has no object.

    HONEST LIMIT: the second pass matches the email only. A row whose `changes` holds
    the customer's phone number or street under some other order's id is not found. In
    this schema that combination does not arise — order edits are recorded against the
    order they touch — but it is a property of today's endpoints, not a guarantee of the
    mechanism, and a future endpoint that writes one customer's details onto another
    object would need a line here.

    Uses `QuerySet.update()`, which bypasses `AuditLog.save()`'s append-only refusal on
    purpose. That is the ONE permitted mutation of this table, and it is permitted at
    three levels that must agree: this function is the single call site
    (`test_audit_guard.py` walks the AST of every production module to prove it), the
    database trigger permits `changes` and no other column, and the GDPR reason is
    written down here.
    """
    from apps.core.models import AuditLog

    matches = Q(pk__in=[])
    for model_label, object_ids in model_labels_and_ids:
        ids = [str(i) for i in object_ids]
        if ids:
            matches |= Q(model_label=model_label, object_id__in=ids)
    if email:
        matches |= Q(_changes_text__icontains=email)

    rows = (
        AuditLog.objects.annotate(_changes_text=Cast("changes", TextField()))
        .filter(matches)
        .exclude(changes={})
    )
    redacted = 0
    for row in rows:
        blanked = {key: REDACTED for key in row.changes}
        if blanked == row.changes:
            continue  # already redacted — idempotent, same property the sweep needs
        AuditLog.objects.filter(pk=row.pk).update(changes=blanked)
        redacted += 1
    return redacted


# HTTP methods that cannot change state. Mirrors the set in
# `apps/accounts/tests/test_admin_surface_guard.py`; kept as a literal rather than
# imported, because production code must not import from the test package.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# What each HTTP method is called in an audit row when the view does not name its own
# action. Verbs rather than methods so a human reading the table sees intent.
_DEFAULT_ACTIONS = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
    "GET": "read",
}


class AdminAuditMixin:
    """Mix into every admin view. Writes one row per successful request.

    Applied FIRST in the bases list (`class X(AdminAuditMixin, APIView)`) so its
    `dispatch` wraps the view's. `test_audit_guard.py` asserts that every view on the
    admin surface carries it, in both directions.

    ── THE FOUR KNOBS ──────────────────────────────────────────────────────────────

    * `audit_reads` — opt in to auditing GETs. PII-bearing endpoints only.
    * `audit_action` — the verb stored in the row. Defaults to a verb derived from the
      HTTP method, which is right for CRUD and useless for `POST .../freight/waive/`,
      so the money endpoints name themselves.
    * `audit_model_label` — `"app_label.modelname"`. Derived from the view's queryset
      or serializer when it has one; declared explicitly by the plain `APIView`s.
    * `audit_allowlist` / `audit_serializers` — which body keys may be stored. See the
      module docstring for why this is an allowlist and nothing else.

    ── WHY IT WRITES ONLY ON 2xx ───────────────────────────────────────────────────

    A refused request changed nothing, and a table where "tried and was denied" looks
    the same as "did it" answers the wrong question. Denials are not lost: 403s and
    401s already reach `apps.security` through the permission and authentication
    layers, and a validation 400 is not a security event at all. The row here means an
    action HAPPENED.
    """

    audit_reads: bool = False
    audit_action: str = ""
    audit_model_label: str = ""
    audit_allowlist: tuple[str, ...] = ()
    # Serializer classes that parse this view's REQUEST BODY. Defaults to
    # `(serializer_class,)`. Declared explicitly by the views whose `serializer_class`
    # describes the RESPONSE (staff invites) or that use several body shapes on
    # different routes (stock: create vs adjust). This tuple is what
    # `test_audit_guard.py` checks allowlisted keys against, so a view that hides its
    # real body serializer from it is hiding it from the write-only check too.
    audit_serializers: tuple[type, ...] = ()

    # -- wiring ------------------------------------------------------------------

    def dispatch(self, request, *args, **kwargs):
        """One transaction around the request; the row written inside it.

        The audit write happens after `super().dispatch()` because that is the only
        point at which the outcome is known — the status code, the created object's id,
        the number of rows a list returned. It is still the SAME transaction, so a
        failure here rolls the mutation back. See the module docstring.
        """
        if request.method.upper() in _SAFE_METHODS and not self.audit_reads:
            return super().dispatch(request, *args, **kwargs)
        if request.method.upper() in {"HEAD", "OPTIONS"}:
            # `audit_reads` means "this endpoint serves PII"; a metadata probe serves
            # none, and auditing OPTIONS would fill the table with CORS preflights.
            return super().dispatch(request, *args, **kwargs)
        with transaction.atomic():
            response = super().dispatch(request, *args, **kwargs)
            if 200 <= response.status_code < 300:
                self._write_audit_row(response)
            return response

    def _write_audit_row(self, response) -> None:
        request = self.request  # the DRF Request; `self.request` is set by initialize()
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            # Not reachable through any routed admin view (all of them authenticate),
            # but the mixin must not turn a surprise into a 500 that rolls back a
            # legitimate write. Nothing to attribute means nothing to record.
            return
        record_audit(
            actor=user,
            actor_email=getattr(user, "email", "") or "",
            token_jti=self._token_jti(),
            client_ip=self._client_ip(),
            model_label=self.resolve_model_label(),
            object_id=self._object_id(response),
            action=self.resolve_action(),
            changes=self._changes(response),
        )

    # -- the pieces of a row -----------------------------------------------------

    def _token_jti(self) -> str:
        """The `jti` of the access token that made this request, or "".

        `request.auth` is the validated token object for every JWT authentication class
        in this project. It is `None` when a test uses `force_authenticate`, and an
        empty jti is the honest record of that: there was no token.
        """
        from rest_framework_simplejwt.settings import api_settings

        token = getattr(self.request, "auth", None)
        if token is None:
            return ""
        try:
            return str(token.get(api_settings.JTI_CLAIM) or "")[:64]
        except AttributeError:
            return ""

    def _client_ip(self) -> str:
        from apps.accounts.throttling import client_ip

        return client_ip(self.request)[:45]

    def resolve_action(self) -> str:
        """`audit_action`, else the DRF viewset action, else a verb for the method.

        The viewset action is preferred over the method verb because a router maps
        `POST /stock/1/adjust/` and `POST /stock/` onto the same class and the same
        method — "create" for both would make the single most consequential inventory
        operation indistinguishable from adding a row.
        """
        if self.audit_action:
            return self.audit_action[:64]
        action = getattr(self, "action", None)
        if action:
            return str(action)[:64]
        return _DEFAULT_ACTIONS.get(self.request.method.upper(), self.request.method.lower())

    def resolve_model_label(self) -> str:
        """`app_label.modelname`, derived where possible and declared where not."""
        if self.audit_model_label:
            return self.audit_model_label[:100]
        queryset = getattr(self, "queryset", None)
        if queryset is not None:
            return queryset.model._meta.label_lower
        serializer_class = getattr(self, "serializer_class", None)
        model = getattr(getattr(serializer_class, "Meta", None), "model", None)
        if model is not None:
            return model._meta.label_lower
        return ""

    def _object_id(self, response) -> str:
        """Which object this row is about.

        From the URL for anything addressed by one; from the response body for a
        create, which is the only case where the id did not exist when the request
        arrived. Reading `id` out of the response is NOT storing the payload — it is
        the one field needed to make the row point at something.
        """
        lookup = getattr(self, "lookup_url_kwarg", None) or getattr(self, "lookup_field", "pk")
        for key in (lookup, "pk", "number", "slug", "id"):
            if key in self.kwargs:
                return str(self.kwargs[key])[:64]
        data = getattr(response, "data", None)
        if isinstance(data, dict) and data.get("id") is not None:
            return str(data["id"])[:64]
        return ""

    def audit_body_serializers(self) -> tuple[type, ...]:
        """The serializer classes that parse this view's request body."""
        if self.audit_serializers:
            return tuple(self.audit_serializers)
        serializer_class = getattr(self, "serializer_class", None)
        return (serializer_class,) if serializer_class is not None else ()

    def resolve_allowlist(self) -> tuple[str, ...]:
        """View-level keys plus every body serializer's, de-duplicated and ordered."""
        keys: list[str] = list(self.audit_allowlist)
        for serializer_class in self.audit_body_serializers():
            keys.extend(getattr(serializer_class, "audit_allowlist", ()))
        return tuple(dict.fromkeys(keys))

    def _changes(self, response) -> dict:
        if self.request.method.upper() in _SAFE_METHODS:
            return self._read_changes(response)
        return build_changes(self.request.data, self.resolve_allowlist())

    def _read_changes(self, response) -> dict:
        """What a read recorded: the query, and how much came back.

        The query parameters are the point. "Support opened order TC-100038" is mildly
        interesting; "Support listed every order matching `@gmail.com`, 3,400 results"
        is the sentence an audit log exists to be able to write. The result count is the
        scale of what left the building, and it is a COUNT — never the rows.
        """
        data = getattr(response, "data", None)
        changes: dict = {"query": {k: _jsonable(v) for k, v in self.request.query_params.items()}}
        if isinstance(data, dict) and isinstance(data.get("count"), int):
            changes["result_count"] = data["count"]   # DRF pagination
        elif isinstance(data, dict) and isinstance(data.get("results"), list):
            changes["result_count"] = len(data["results"])
        elif isinstance(data, list):
            changes["result_count"] = len(data)
        return changes
