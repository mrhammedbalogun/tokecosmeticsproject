"""The adapter interface every ad platform implements.

An adapter is a pure translation from `ConversionPayload` to one vendor's JSON, plus the
handful of facts about that vendor's HTTP (where it goes, how it authenticates, and what
counts as "accepted"). It holds no database access and no policy: whether an event should
be sent at all is decided in `events.py` before an adapter is ever constructed.

That split is what makes the adapters testable against recorded fixtures without a
database, a network, or a Celery worker — which matters here more than usual, because
none of these four APIs can be exercised without live credentials for a real ad account.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from apps.marketing.channels.http import TransportFailure, post_json
from apps.marketing.payloads import ConversionPayload


@dataclass(frozen=True)
class ChannelResult:
    """What happened, in terms the outbox understands.

    `retryable` is the whole point of this type. A 400 means the body was wrong and will
    be wrong again forever — retrying it burns a worker every few minutes for nothing. A
    503 or a timeout means try later. Vendors disagree about which of their failures are
    which, so each adapter decides rather than the task guessing from a status code.
    """

    ok: bool
    status: int | None = None
    excerpt: str = ""
    retryable: bool = False


class ConversionChannel:
    code: str = ""

    def __init__(self, *, pixel_id: str, access_token: str, test_event_code: str = ""):
        self.pixel_id = pixel_id
        self.access_token = access_token
        self.test_event_code = test_event_code

    # --- the two things every adapter must implement -------------------------------

    def build(self, payload: ConversionPayload) -> dict:
        """This vendor's request body for one event."""
        raise NotImplementedError

    def endpoint(self) -> str:
        raise NotImplementedError

    # --- overridable transport details ----------------------------------------------

    def headers(self) -> dict:
        return {"Content-Type": "application/json"}

    def interpret(self, response: httpx.Response) -> ChannelResult:
        """Default reading of a vendor response: 2xx is accepted, 5xx and 429 are worth
        retrying, everything else is our fault and will not improve.

        Overridden by any vendor that answers 200 while refusing the event — which is
        common enough in this corner of the industry to be the reason this is a method.
        """
        excerpt = (response.text or "")[:1000]
        if 200 <= response.status_code < 300:
            return ChannelResult(ok=True, status=response.status_code, excerpt=excerpt)
        retryable = response.status_code >= 500 or response.status_code == 429
        return ChannelResult(
            ok=False, status=response.status_code, excerpt=excerpt, retryable=retryable
        )

    # --- the one entry point the task calls -----------------------------------------

    def send(self, body: dict, *, timeout: float | None = None, retries: int | None = None) -> ChannelResult:
        """Deliver one event.

        `timeout` and `retries` are overridable for ONE caller: the admin's "Send test
        event" button. That request runs inside `AdminAuditMixin.dispatch`'s transaction,
        so the default budget (10s, one retry, ~20s worst case) would hold a Postgres
        connection idle-in-transaction for twenty seconds while a vendor times out. The
        Celery path has no such constraint and keeps the generous default — there, giving
        up early loses a sale.
        """
        kwargs = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        if retries is not None:
            kwargs["retries"] = retries
        try:
            response = post_json(self.endpoint(), json=body, headers=self.headers(), **kwargs)
        except TransportFailure as exc:
            # Never reached the vendor, or never got an answer. Always worth another go:
            # the event id makes a duplicate harmless, and silence makes a sale vanish.
            return ChannelResult(ok=False, excerpt=str(exc)[:1000], retryable=True)
        return self.interpret(response)
