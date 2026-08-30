"""Each vendor's body shape, pinned against what their documentation says.

None of these four APIs can be exercised without a live ad account, so this file is the
only thing standing between a plausible-looking payload and a channel that reports zero
conversions for a month. Every assertion is a rule taken from the vendor's own docs and
each one, if broken, fails silently in production.
"""
from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from apps.marketing.channels.ga4 import Ga4Channel
from apps.marketing.channels.meta import MetaChannel, build_fbc
from apps.marketing.channels.snapchat import SnapchatChannel
from apps.marketing.channels.tiktok import TikTokChannel
from apps.marketing.payloads import PURCHASE, ContentItem, ConversionPayload, UserSignals


def payload(**kwargs) -> ConversionPayload:
    defaults = dict(
        event_name=PURCHASE,
        event_id="TC-100147",
        event_time=1700000000,
        source_url="https://tokecosmetics.com/checkout/confirmation/TC-100147",
        currency="NGN",
        value=Decimal("47500.00"),
        order_number="TC-100147",
        contents=(ContentItem(content_id="SKU-1", quantity=2, item_price=Decimal("2500.00"),
                              name="Radiance Serum"),),
        user=UserSignals(
            email="Amina@Example.com",
            phone="+2348012345678",
            first_name="Amina",
            last_name="Bello",
            city="Lekki",
            state="Lagos",
            country="NG",
            external_id="42",
            client_ip="102.89.1.1",
            client_user_agent="Mozilla/5.0 (test)",
            click_ids={"fbclid": "FBCLICK", "ttclid": "TTCLICK", "sccid": "SCCLICK",
                       "ts": 1699999000},
            pixel_cookies={"fbp": "fb.1.1699999000.111", "ttp": "ttp-abc", "scid": "scid-abc"},
        ),
    )
    defaults.update(kwargs)
    return ConversionPayload(**defaults)


# --- Meta ---------------------------------------------------------------------------


def test_meta_hashed_identifiers_are_arrays_and_raw_ones_are_not():
    """Meta accepts a bare string for `em` and matches NOTHING with it. The array is
    not a stylistic choice."""
    body = MetaChannel(pixel_id="P1", access_token="T").build(payload())
    user = body["data"][0]["user_data"]
    for key in ("em", "ph", "fn", "ln", "ct", "st", "country", "external_id"):
        assert isinstance(user[key], list), f"{key} must be a list"
    for key in ("client_ip_address", "client_user_agent", "fbc", "fbp"):
        assert isinstance(user[key], str), f"{key} must be a bare string"


def test_meta_never_hashes_the_click_id_or_the_cookies_or_the_ip():
    """The silent killer. Hashing these produces no error and destroys the match."""
    body = MetaChannel(pixel_id="P1", access_token="T").build(payload())
    user = body["data"][0]["user_data"]
    assert user["fbp"] == "fb.1.1699999000.111"
    assert user["client_ip_address"] == "102.89.1.1"
    assert user["client_user_agent"] == "Mozilla/5.0 (test)"


def test_meta_prefers_the_pixels_own_fbc_cookie_when_the_pixel_did_run():
    """The cookie is what the BROWSER-side event carried, and a mismatched pair is worse
    for one visitor than either value alone. Ours is strictly the fallback."""
    signals = payload().user
    with_cookie = payload(user=UserSignals(
        email=signals.email,
        click_ids=signals.click_ids,
        pixel_cookies={**signals.pixel_cookies, "fbc": "fb.1.1699000000.REALCOOKIE"},
    ))
    body = MetaChannel(pixel_id="P1", access_token="T").build(with_cookie)
    assert body["data"][0]["user_data"]["fbc"] == "fb.1.1699000000.REALCOOKIE"


def test_meta_builds_fbc_from_our_own_click_id_when_the_pixel_never_ran():
    """The biggest match-quality win available server-side: an ad blocker kills the
    `_fbc` cookie, but our proxy still saw the `?fbclid=` on the landing navigation."""
    signals = payload().user
    no_cookie = payload(user=UserSignals(
        email=signals.email, click_ids=signals.click_ids, pixel_cookies={},
    ))
    body = MetaChannel(pixel_id="P1", access_token="T").build(no_cookie)
    assert body["data"][0]["user_data"]["fbc"] == "fb.1.1699999000000.FBCLICK"


def test_build_fbc_uses_the_registrable_domain_index_and_milliseconds():
    # `fb.1.` — 1 is tokecosmetics.com. A different index disagrees with what Meta's own
    # pixel would have written for the same visitor.
    assert build_fbc("ABC", 1700000000) == "fb.1.1700000000000.ABC"
    assert build_fbc("", 1700000000) == ""


def test_meta_omits_identifiers_it_does_not_have_rather_than_sending_empty_ones():
    body = MetaChannel(pixel_id="P1", access_token="T").build(
        payload(user=UserSignals(email="a@b.com"))
    )
    user = body["data"][0]["user_data"]
    assert "em" in user
    assert "ph" not in user and "fn" not in user and "fbc" not in user


def test_meta_value_is_a_number_and_carries_the_order_id():
    body = MetaChannel(pixel_id="P1", access_token="T").build(payload())
    custom = body["data"][0]["custom_data"]
    assert custom["value"] == 47500.0 and isinstance(custom["value"], float)
    assert custom["currency"] == "NGN"
    assert custom["content_ids"] == ["SKU-1"]
    assert custom["order_id"] == "TC-100147"


def test_meta_endpoint_pins_the_graph_version_from_settings(settings):
    settings.META_GRAPH_API_VERSION = "v26.0"
    url = MetaChannel(pixel_id="P1", access_token="T").endpoint()
    assert url.startswith("https://graph.facebook.com/v26.0/P1/events?access_token=T")


def test_meta_test_event_code_only_appears_when_set():
    assert "test_event_code" not in MetaChannel(pixel_id="P1", access_token="T").build(payload())
    body = MetaChannel(pixel_id="P1", access_token="T", test_event_code="TEST9").build(payload())
    assert body["test_event_code"] == "TEST9"


# --- TikTok -------------------------------------------------------------------------


def test_tiktok_uses_the_2_0_shape_and_not_the_v1_2_one():
    """The version trap. `pixel_code` + `context` is Events API 1.2 and is what almost
    every blog post still shows; the v1.3 endpoint wants `event_source_id` + `data[]`."""
    body = TikTokChannel(pixel_id="P1", access_token="T").build(payload())
    assert body["event_source"] == "web"
    assert body["event_source_id"] == "P1"
    assert "pixel_code" not in body and "context" not in body
    event = body["data"][0]
    assert set(event) >= {"event", "event_time", "event_id", "user", "page", "properties"}
    assert isinstance(event["event_time"], int)


def test_tiktok_purchase_is_complete_payment_not_place_an_order():
    """Ours fires when money is taken, not when an order is submitted. Sending
    PlaceAnOrder would teach TikTok to optimise for a step the shop is not paid at."""
    body = TikTokChannel(pixel_id="P1", access_token="T").build(payload())
    assert body["data"][0]["event"] == "CompletePayment"


def test_tiktok_hashes_email_and_phone_but_not_the_click_id():
    user = TikTokChannel(pixel_id="P1", access_token="T").build(payload())["data"][0]["user"]
    assert len(user["email"]) == 64 and len(user["phone"]) == 64
    assert user["ttclid"] == "TTCLICK"
    assert user["ttp"] == "ttp-abc"
    assert user["ip"] == "102.89.1.1"


def test_tiktok_always_sends_a_page_url_because_web_events_require_one():
    body = TikTokChannel(pixel_id="P1", access_token="T").build(payload())
    assert body["data"][0]["page"]["url"].startswith("https://")


def test_tiktok_treats_a_business_refusal_inside_an_http_200_as_a_failure():
    """TikTok answers 200 with a non-zero `code` for a bad pixel id or an expired token.
    Judging on the HTTP status alone marks every one of those 'sent' — an integration
    that looks healthy while the ad account receives nothing."""
    channel = TikTokChannel(pixel_id="P1", access_token="T")
    refused = httpx.Response(200, json={"code": 40100, "message": "Access token invalid"})
    result = channel.interpret(refused)
    assert result.ok is False
    assert result.retryable is False       # our fault; retrying cannot help
    assert "40100" in result.excerpt

    accepted = httpx.Response(200, json={"code": 0, "message": "OK"})
    assert channel.interpret(accepted).ok is True


def test_tiktok_server_side_envelope_codes_are_retryable():
    channel = TikTokChannel(pixel_id="P1", access_token="T")
    result = channel.interpret(httpx.Response(200, json={"code": 50000, "message": "oops"}))
    assert result.ok is False and result.retryable is True


# --- Snapchat -----------------------------------------------------------------------


def test_snapchat_event_names_are_upper_snake_and_add_cart_not_add_to_cart():
    from apps.marketing.channels.snapchat import EVENT_NAMES
    from apps.marketing.payloads import ADD_TO_CART

    assert EVENT_NAMES[PURCHASE] == "PURCHASE"
    assert EVENT_NAMES[ADD_TO_CART] == "ADD_CART"


def test_snapchat_value_is_a_string_and_action_source_is_uppercase():
    """The one place a copy-paste from meta.py breaks: Snap's schema types `value` as a
    string and a JSON number is a 400."""
    event = SnapchatChannel(pixel_id="P1", access_token="T").build(payload())["data"][0]
    assert event["custom_data"]["value"] == "47500.00"
    assert isinstance(event["custom_data"]["value"], str)
    assert event["action_source"] == "WEB"


def test_snapchat_hashed_identifiers_are_arrays_and_the_click_id_is_raw():
    user = SnapchatChannel(pixel_id="P1", access_token="T").build(payload())["data"][0]["user_data"]
    assert isinstance(user["em"], list) and len(user["em"][0]) == 64
    assert isinstance(user["ph"], list)
    assert user["sc_click_id"] == "SCCLICK"
    assert user["sc_cookie1"] == "scid-abc"


def test_snapchat_endpoint_is_v3():
    """v2 was deprecated in early 2025 and is what most third-party guides still show."""
    url = SnapchatChannel(pixel_id="P1", access_token="T").endpoint()
    assert url == "https://tr.snapchat.com/v3/P1/events?access_token=T"


# --- GA4 ----------------------------------------------------------------------------


def test_ga4_timestamp_is_microseconds_not_seconds():
    """Seconds here puts the event fifty thousand years out and GA4 discards it in
    silence — the Measurement Protocol returns 204 for a malformed event too."""
    body = Ga4Channel(pixel_id="G-1", access_token="S").build(payload())
    assert body["timestamp_micros"] == 1700000000 * 1_000_000


def test_ga4_purchase_uses_googles_own_vocabulary():
    body = Ga4Channel(pixel_id="G-1", access_token="S").build(payload())
    event = body["events"][0]
    assert event["name"] == "purchase"
    assert event["params"]["transaction_id"] == "TC-100147"
    assert event["params"]["items"][0]["item_id"] == "SKU-1"


def test_ga4_synthesises_a_stable_client_id_when_the_browser_never_supplied_one():
    """A webhook-driven purchase has no `_ga` cookie. The fallback must be STABLE, or a
    retry invents a second 'user' for the same sale."""
    channel = Ga4Channel(pixel_id="G-1", access_token="S")
    first = channel.build(payload(ga_client_id=""))["client_id"]
    second = channel.build(payload(ga_client_id=""))["client_id"]
    assert first == second
    assert "." in first
    # The real cookie value wins whenever it exists.
    assert channel.build(payload(ga_client_id="111.222"))["client_id"] == "111.222"


def test_ga4_debug_endpoint_turns_validation_messages_into_a_failure():
    channel = Ga4Channel(pixel_id="G-1", access_token="S", debug=True)
    assert "debug/mp/collect" in channel.endpoint()
    bad = httpx.Response(200, json={"validationMessages": [{"description": "bad param"}]})
    assert channel.interpret(bad).ok is False
    good = httpx.Response(200, json={"validationMessages": []})
    assert channel.interpret(good).ok is True


# --- shared behaviour ---------------------------------------------------------------


@pytest.mark.parametrize("cls", [MetaChannel, TikTokChannel, SnapchatChannel, Ga4Channel])
def test_every_adapter_translates_the_canonical_event_names(cls):
    """No adapter may be missing a name: a KeyError here would raise inside the Celery
    task and turn a missing conversion into a failed one."""
    from apps.marketing.payloads import CANONICAL_EVENTS

    channel = cls(pixel_id="P1", access_token="T")
    for name in CANONICAL_EVENTS:
        channel.build(payload(event_name=name))


@pytest.mark.parametrize("cls", [MetaChannel, TikTokChannel, SnapchatChannel, Ga4Channel])
def test_a_5xx_is_retryable_and_a_400_is_not(cls):
    channel = cls(pixel_id="P1", access_token="T")
    assert channel.interpret(httpx.Response(503, text="down")).retryable is True
    assert channel.interpret(httpx.Response(400, text="bad body")).retryable is False
