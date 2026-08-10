"""The sniff decides what a file IS. Today's code decides by filename extension, which
is client input — every case below that flips on renaming is the reason this exists."""
import pytest

from apps.cms.video_sniff import is_faststart, sniff_video_container

# A real MP4 begins with a box-length then "ftyp" at offset 4.
MP4_HEAD = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
WEBM_HEAD = b"\x1a\x45\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x23B\x86\x81\x01"
PNG_HEAD = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


@pytest.mark.parametrize(
    "head,expected",
    [
        (MP4_HEAD, "mp4"),
        (WEBM_HEAD, "webm"),
        (PNG_HEAD, None),
        (b"hello world, plainly not a video", None),
        (b"", None),
        (b"\x00\x00\x00\x20ftyp", "mp4"),      # truncated but identifiable
        (b"\x00\x00\x00\x20ftyq" + b"\x00" * 8, None),  # one byte off
    ],
)
def test_sniff_video_container(head, expected):
    assert sniff_video_container(head) == expected


def test_extension_cannot_override_the_bytes():
    """The whole point: naming a PNG .mp4 must not make it a video, and naming an MP4
    .png must not stop it being one. The sniff never sees a filename."""
    assert sniff_video_container(PNG_HEAD) is None
    assert sniff_video_container(MP4_HEAD) == "mp4"


def test_faststart_detection():
    """moov before mdat means the browser can start playing before the file finishes."""
    assert is_faststart(b"\x00\x00\x00\x20ftypisom" + b"\x00\x00\x01\x00moov" + b"x" * 40)
    assert not is_faststart(b"\x00\x00\x00\x20ftypisom" + b"\x00\x00\x01\x00mdat" + b"x" * 40)
    # Neither box in the window: unknown, and we do not cry wolf.
    assert is_faststart(b"\x00\x00\x00\x20ftypisom" + b"x" * 40)
