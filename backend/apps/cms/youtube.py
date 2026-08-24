"""Turning whatever somebody pastes into a YouTube video id.

The training library (2026-08-23) stores a VIDEO ID, not a URL, as its source of
truth. A pasted link arrives in a dozen shapes — `watch?v=`, `youtu.be/`, `shorts/`,
`embed/`, `live/`, with or without a scheme, dragging `?si=` share-tracking and `&t=`
timestamps along — and every one of them names the same eleven characters. Parsing
once at save time means the player, the thumbnail and the "open on YouTube" link can
all be BUILT from the id and can never disagree with each other, and a link that does
not contain a video id is refused at the moment the person who typed it is still
looking at the form, rather than becoming a broken player some staff member finds
next month.

Parsing is also the safety boundary. The admin renders an `<iframe src=…>` from this
value; deriving that `src` from `https://www.youtube-nocookie.com/embed/<id>` where
`<id>` matched `[A-Za-z0-9_-]{11}` means no pasted URL — however malicious — ever
reaches an iframe attribute. (CSP `frame-src` in the admin pins the YouTube origin
too; this is the belt to that suspender.)

Deliberately NOT here: a network check that the video exists and is public. It would
make saving a training depend on YouTube being reachable from the Django box, and a
video can be deleted or privated AFTER saving anyway — the player's own "unavailable"
message is the honest state either way.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

# YouTube video ids: 11 characters of base64url. YouTube has never documented this as
# a contract, but every id it has ever issued matches, and accepting anything looser
# would let a malformed paste through to the iframe.
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Hosts a YouTube video link can carry. An allowlist, not a "contains youtube"
# heuristic: `notyoutube.com` and `youtube.com.evil.example` must not pass.
_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
    }
)

# Path prefixes that carry the id as their next segment: /shorts/<id>, /embed/<id>,
# /live/<id>, /v/<id> (the ancient Flash-era form still found in old docs).
_PATH_FORMS = ("shorts", "embed", "live", "v")


def parse_youtube_video_id(raw: str) -> str | None:
    """The video id in a pasted YouTube link, or None if there is not one.

    None covers both "not YouTube at all" and "YouTube but no single video" — a
    channel page, a playlist link without `v=`, a bare `youtube.com`. The caller's
    error message treats them the same, because the fix is the same: paste the link
    of one specific video.
    """
    text = (raw or "").strip()
    if not text:
        return None
    # People paste links without a scheme ("youtu.be/abc…") often enough that
    # refusing them would just teach everyone to add https:// by hand.
    if "://" not in text:
        text = f"https://{text}"

    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if host not in _HOSTS:
        return None

    segments = [s for s in parts.path.split("/") if s]

    # https://youtu.be/<id>
    if host == "youtu.be":
        candidate = segments[0] if segments else ""
        return candidate if _VIDEO_ID.match(candidate) else None

    # https://www.youtube.com/watch?v=<id>  (the canonical form, params in any order)
    if segments and segments[0] == "watch":
        candidate = (parse_qs(parts.query).get("v") or [""])[0]
        return candidate if _VIDEO_ID.match(candidate) else None

    # https://www.youtube.com/shorts/<id>, /embed/<id>, /live/<id>, /v/<id>
    if len(segments) >= 2 and segments[0] in _PATH_FORMS:
        candidate = segments[1]
        return candidate if _VIDEO_ID.match(candidate) else None

    return None


def canonical_watch_url(video_id: str) -> str:
    """The one spelling of the link this system stores and shows.

    `watch?v=` rather than `youtu.be` because it is the form YouTube itself puts in
    the address bar — the least surprising thing to see back after pasting.
    """
    return f"https://www.youtube.com/watch?v={video_id}"
