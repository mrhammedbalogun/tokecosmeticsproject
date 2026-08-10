"""What a video file IS, decided by its bytes (2026-08-09).

`admin_serializers.sniff_kind` decides video by filename extension, which is whatever
the client typed. That is fine while Django holds the whole file and Pillow can rule
images in — but the presigned path never sees the file as an upload, only as bytes in
S3, and a stricter answer is cheap: both containers announce themselves in their first
handful of bytes.

Deliberately operates on a HEAD SLICE, not a file object: the caller range-reads ~256 KB
from S3 rather than pulling 128 MB across the Atlantic on every upload.
"""

# ISO base media (mp4/m4v/mov): a box length, then the "ftyp" type at offset 4.
_MP4_BRAND_OFFSET = 4
_MP4_BRAND = b"ftyp"
# Matroska/WebM: the EBML header magic, at offset 0.
_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"

VIDEO_CONTENT_TYPES = {"mp4": "video/mp4", "webm": "video/webm"}
VIDEO_EXTENSIONS = {"mp4": ".mp4", "webm": ".webm"}


def sniff_video_container(head: bytes) -> str | None:
    """"mp4" | "webm" | None. `head` is the first bytes of the file; a few dozen suffice."""
    if head.startswith(_WEBM_MAGIC):
        return "webm"
    if head[_MP4_BRAND_OFFSET:_MP4_BRAND_OFFSET + len(_MP4_BRAND)] == _MP4_BRAND:
        return "mp4"
    return None


def is_faststart(head: bytes) -> bool:
    """True when the MP4 index (`moov`) precedes the media data (`mdat`).

    Without it a browser must download the entire file before playing a single frame —
    for a 3-minute film on mobile data that reads as "the video is broken". Returns True
    when neither box appears in the window: unknown is not a reason to warn.
    """
    moov = head.find(b"moov")
    mdat = head.find(b"mdat")
    if mdat == -1:
        return True
    if moov == -1:
        return False
    return moov < mdat
