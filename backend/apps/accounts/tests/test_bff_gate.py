"""The BFF shared-secret gate on the two admin endpoints with exactly one caller.

WHAT THIS IS, AND WHAT IT IS NOT. It is an ANTI-ABUSE gate, not an authentication
control, and the distinction decides every design choice below. The security controls on
`/auth/admin-token/` are Turnstile, the password, TOTP and the audience claim; a leaked
BFF secret costs an attacker nothing but the right to be rate-limited like everybody
else. Nothing here should ever be described as authenticating the caller.

WHY IT EXISTS. Both endpoints perform an outbound Turnstile siteverify call before they
do anything else, and both are reachable by anyone. Metering that by request volume in
Django is not available: the admin app calls the API **server-side**, so every legitimate
staff login shares one Vercel egress address with every attacker, and a volume cap keyed
on it is a free staff lockout — which an adversarial review already found and which is
why both admin throttles count *failed credentials* rather than requests.

So the volume gap was real and unmeterable. The observation that closes it is structural:
these two endpoints have exactly ONE legitimate caller in the world, the admin BFF. An
endpoint with a single known server-side caller does not need a volume cap; it needs
proof of coming from that caller. Junk without the header now costs a constant-time
compare instead of a 5-second-timeout HTTPS round trip.

UNSET MEANS OFF, matching `TURNSTILE_SECRET` exactly. That is the rollout switch: the
backend can deploy before the admin app sends the header, and it is also the break-glass
if the two ever disagree.
"""
import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PW = "Str0ng!pass9"
SECRET = "s3cret-shared-with-the-bff-and-nobody-else"
HEADER = "X-Admin-BFF-Secret"

ADMIN_TOKEN = "/api/v1/auth/admin-token/"
ACCEPT = "/api/v1/admin/staff/invites/accept/"


@pytest.fixture
def staff(django_user_model):
    user = django_user_model.objects.create_user(
        email="owner@toke.test", password=PW, is_staff=True
    )
    user.groups.add(Group.objects.get(name="Owner"))
    return user


@pytest.fixture
def gate_on(settings):
    settings.ADMIN_BFF_SECRET = SECRET
    return SECRET


def post(path, body, secret=None):
    headers = {"HTTP_X_ADMIN_BFF_SECRET": secret} if secret is not None else {}
    return APIClient().post(path, body, format="json", **headers)


# --- the gate itself ----------------------------------------------------------


def test_a_request_without_the_header_is_refused(gate_on, staff):
    response = post(ADMIN_TOKEN, {"email": staff.email, "password": PW})

    assert response.status_code == 403


def test_a_request_with_the_wrong_secret_is_refused(gate_on, staff):
    response = post(ADMIN_TOKEN, {"email": staff.email, "password": PW}, secret="wrong")

    assert response.status_code == 403


def test_the_correct_secret_lets_the_request_through_to_the_credential_check(gate_on, staff):
    """Through the gate, not past the fences. Turnstile is unset in tests, so what this
    proves is that the request reached the password check and the password was accepted —
    the gate is a doorman, not a door."""
    response = post(ADMIN_TOKEN, {"email": staff.email, "password": PW}, secret=SECRET)

    assert response.status_code == 200, response.data
    assert "preauth_token" in response.data


def test_the_refusal_is_indistinguishable_from_a_turnstile_refusal(gate_on, staff):
    """No oracle. A prober must not be able to learn from the response that this endpoint
    wants a secret header at all — otherwise the gate advertises itself, and the first
    thing an attacker does with that knowledge is go looking for the value.

    The operator's diagnostic is the log line and the Sentry event, not the body. This is
    written down in the runbook because "Human verification failed" on EVERY staff login
    at once means the BFF secret, not Turnstile.
    """
    from apps.accounts.turnstile import _DENIED

    refused = post(ADMIN_TOKEN, {"email": staff.email, "password": PW})

    assert refused.status_code == 403
    assert refused.data["detail"] == _DENIED


def test_the_gate_runs_before_turnstile_so_junk_costs_no_siteverify_call(
    gate_on, staff, settings, monkeypatch
):
    """THE ENTIRE POINT OF THE FEATURE, asserted rather than assumed.

    A request without the header must be refused *before* the outbound siteverify HTTPS
    call is made. If the order were reversed the gate would still refuse the request and
    every other test here would still pass, while the cost it exists to remove was still
    being paid on every junk request.
    """
    settings.TURNSTILE_ADMIN_SECRET = "sk-admin"
    calls = []
    monkeypatch.setattr(
        "apps.accounts.turnstile.httpx.post",
        lambda *a, **kw: calls.append(kw) or pytest.fail("siteverify was called"),
    )

    # A token MUST be present in the body. Without one, `require_turnstile` refuses on
    # the missing-token branch before it ever reaches `httpx.post`, so the assertion
    # below would hold with no gate at all — the test would pass while proving nothing.
    # Caught exactly that way on the first RED run.
    response = post(
        ADMIN_TOKEN,
        {"email": staff.email, "password": PW, "turnstile_token": "would-be-verified"},
    )

    assert response.status_code == 403
    assert calls == []


def test_an_unset_secret_disables_the_gate_entirely(settings, staff):
    """The rollout switch and the break-glass, and the same contract `TURNSTILE_SECRET`
    has. The backend must be deployable before the admin app sends the header."""
    settings.ADMIN_BFF_SECRET = ""

    response = post(ADMIN_TOKEN, {"email": staff.email, "password": PW})

    assert response.status_code == 200, response.data


def test_the_gate_does_not_touch_the_failure_throttles(gate_on, staff):
    """A missing header is not a credential guess. Counting it would hand back exactly
    the free-lockout primitive that made these throttles failure-counting in the first
    place: anonymous junk could fill the shared-egress bucket and lock out the staff."""
    from apps.accounts.throttling import AdminLoginEmailThrottle

    for _ in range(12):
        assert post(ADMIN_TOKEN, {"email": staff.email, "password": PW}).status_code == 403

    # The email bucket allows 10 failures/hour. Twelve refusals must have consumed none,
    # so a correct request still succeeds.
    ok = post(ADMIN_TOKEN, {"email": staff.email, "password": PW}, secret=SECRET)
    assert ok.status_code == 200, ok.data
    assert AdminLoginEmailThrottle().record_failure is not None  # sanity: API unchanged


def test_a_refusal_is_logged_at_error_for_sentry(gate_on, staff, caplog):
    """Distinct wording, because this is the one failure whose cause the response body
    deliberately hides. An operator staring at "Human verification failed" needs Sentry
    to say the word 'BFF'."""
    with caplog.at_level("ERROR", logger="apps.security"):
        post(ADMIN_TOKEN, {"email": staff.email, "password": PW})

    assert any("bff" in record.message.lower() for record in caplog.records)


def test_the_secret_is_never_logged(gate_on, staff, caplog):
    with caplog.at_level("DEBUG"):
        post(ADMIN_TOKEN, {"email": staff.email, "password": PW}, secret=SECRET)
        post(ADMIN_TOKEN, {"email": staff.email, "password": PW}, secret="wrong-but-secret")

    blob = " ".join(r.getMessage() for r in caplog.records)
    assert SECRET not in blob
    assert "wrong-but-secret" not in blob


# --- the second endpoint ------------------------------------------------------


def test_accept_invite_is_gated_too(gate_on):
    """Same shape, same sole caller, same unmetered siteverify call. Its own docstring
    already names the gap; this closes it in the same commit rather than leaving a
    second door open for the same reason."""
    response = post(ACCEPT, {"token": "irrelevant", "password": PW})

    assert response.status_code == 403


def test_accept_invite_with_the_secret_reaches_its_own_validation(gate_on):
    """Through the gate and on to the token check, which refuses a bogus token on its
    own merits — proving the gate did not simply swallow the request."""
    from apps.accounts.turnstile import _DENIED

    body = {"token": "not-a-real-token", "password": PW}
    without = post(ACCEPT, body)
    with_secret = post(ACCEPT, body, secret=SECRET)

    # The comparison IS the assertion: the same request refused two different ways, and
    # the only variable is the header. Asserting on the shape of the second body alone
    # would be fragile — DRF answers this endpoint with a list, not a `detail` dict.
    assert _DENIED in str(without.data)
    assert _DENIED not in str(with_secret.data)
