# Presigned Video Uploads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the admin upload videos far larger than Vercel's ~4 MB request-body limit by sending them straight from the browser to S3, verified server-side before they become public — and let each banner choose whether its video loops or waits for a click.

**Architecture:** The browser asks the Django API for a presigned S3 POST whose key is server-generated and pinned exactly, uploads the file directly to a quarantine prefix (`incoming/`) that CloudFront cannot serve, then calls a finalize endpoint. Finalize head-checks the real size, sniffs container magic bytes from a 256 KB ranged read, and copies the object into `catalog/library/` with a server-set Content-Type. Images are untouched and keep their existing full-byte Pillow path.

**Tech Stack:** Django 5 + DRF + boto3 + django-storages (backend), Next.js 16 App Router + TypeScript (admin and storefront), pytest + moto (backend tests), vitest + testing-library (frontend tests).

**Spec:** `docs/superpowers/specs/2026-08-09-presigned-video-uploads-design.md`

## Global Constraints

- **Bucket:** `tokecosmetics-assets-899805259502-eu-west-1-an`, region `eu-west-1`. Private; CloudFront distribution `E3RM3YPEKZS13G` reads it via OAC with the bucket policy scoped to `catalog/*` only.
- **Video ceiling: 128 MB.** One constant, `MAX_VIDEO_BYTES` in `backend/apps/cms/admin_serializers.py`, raised from 80 MB. Both the presigned path and the legacy multipart path read it. Never duplicate this number.
- **Loop warning threshold: 6 MB** (`LOOP_WARN_BYTES`). A warning, never a block.
- **Quarantine prefix:** `incoming/`. **Library prefix:** `catalog/library/`.
- **Allowed video extensions:** `.mp4`, `.webm` only. Never derived from the client's filename — chosen from the sniffed/declared kind.
- **Every S3 delete and copy-source in this feature goes through `backend/apps/cms/s3_uploads.py`.** No boto3 delete anywhere else. The Django container's credential can delete the Postgres backups in `backups/`; this is the seatbelt.
- **Images are out of scope.** Do not modify `admin/src/lib/image.ts`, `sniff_kind`, or `MAX_IMAGE_BYTES`.
- `Banner.video_mode` defaults to `loop` so the migration changes nothing visible on the live homepage.
- Windows dev box: use PowerShell-compatible commands. Backend commands run under `uv`.
- Both Next apps carry `AGENTS.md` warning that this Next version differs from training data — read `node_modules/next/dist/docs/` before writing App Router code.

---

## File Structure

**Backend (new):**
- `backend/apps/cms/video_sniff.py` — pure byte-inspection. No S3, no Django. Container magic + faststart detection.
- `backend/apps/cms/s3_uploads.py` — the only module that talks to S3 for this flow. Key minting, presigned POST, head, ranged read, guarded copy, guarded delete.
- `backend/apps/cms/tests/test_video_sniff.py`
- `backend/apps/cms/tests/test_s3_uploads.py`
- `backend/apps/cms/tests/test_video_upload_api.py`

**Backend (modified):**
- `backend/apps/cms/models.py` — `Banner.video_mode`
- `backend/apps/cms/migrations/0008_banner_video_mode.py` (new; confirm the next number before writing)
- `backend/apps/cms/serializers.py` — expose `video_mode` publicly
- `backend/apps/cms/admin_serializers.py` — raise `MAX_VIDEO_BYTES`; add ticket/finalize serializers; add `video_mode` to the banner admin serializer + audit allowlist
- `backend/apps/cms/admin_views.py` — two `@action` endpoints
- `backend/pyproject.toml` — add `moto` to dev dependencies

**Admin (new):**
- `admin/src/lib/video.ts` — `VIDEO_CAP_BYTES`, `LOOP_WARN_BYTES`, `fileSizeMb` re-export
- `admin/src/lib/upload.ts` — XHR upload with progress and abort
- `admin/src/lib/__tests__/upload.test.ts`

**Admin (modified):**
- `admin/src/lib/csp.ts` — bucket origin in `connect-src`
- `admin/src/lib/banners.ts` — hero guide text
- `admin/src/app/(shell)/content/media/actions.ts` — two server actions
- `admin/src/components/content/MediaLibraryModal.tsx` — video via the new path
- `admin/src/components/content/HomeBannerModal.tsx` — video slot + `video_mode` radio

**Storefront (new):**
- `storefront/src/components/home/ClickToPlayVideo.tsx` — `"use client"`; `TileMedia` is a server component and cannot hold the interaction

**Storefront (modified):**
- `storefront/src/lib/cms.ts` — `video_mode` on `CmsBanner`
- `storefront/src/components/home/TileMedia.tsx`
- `storefront/src/components/home/HeroSlider.tsx`

**Infra (manual, Task 11):** bucket CORS, `incoming/` lifecycle rule, CloudFront response-headers policy.

---

### Task 1: `Banner.video_mode`

Ships on its own: after this task the field exists, defaults to `loop`, and reaches the storefront payload. Nothing renders differently yet.

**Files:**
- Modify: `backend/apps/cms/models.py` (after the `video` field, ~line 154)
- Create: `backend/apps/cms/migrations/0008_banner_video_mode.py`
- Modify: `backend/apps/cms/serializers.py:27-30`
- Modify: `backend/apps/cms/admin_serializers.py` (`BannerAdminSerializer`)
- Test: `backend/apps/cms/tests/test_landing_redesign.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Banner.video_mode` (`"loop"` | `"click"`, default `"loop"`); the same string on the public homepage payload and the admin banner serializer.

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/cms/tests/test_landing_redesign.py`:

```python
@pytest.mark.django_db
def test_banner_video_mode_defaults_to_loop_and_reaches_the_wire():
    """A banner made before this field existed must keep behaving exactly as it did."""
    banner = Banner.objects.create(title="Hero", placement="hero", is_active=True)
    assert banner.video_mode == "loop"

    r = APIClient().get("/api/v1/cms/homepage/")
    assert r.status_code == 200
    hero = next(b for b in r.json()["banners"] if b["placement"] == "hero")
    assert hero["video_mode"] == "loop"


@pytest.mark.django_db
def test_banner_video_mode_accepts_click():
    banner = Banner.objects.create(
        title="Film", placement="hero", is_active=True, video_mode="click",
    )
    banner.full_clean()
    assert banner.video_mode == "click"
```

Ensure the file imports `Banner` and `APIClient`; both are already used in it.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; uv run pytest apps/cms/tests/test_landing_redesign.py -k video_mode -v`
Expected: FAIL — `AttributeError` / `TypeError: 'video_mode' is an invalid keyword argument`.

- [ ] **Step 3: Add the model field**

In `backend/apps/cms/models.py`, immediately after the `video = models.FileField(...)` block:

```python
    # 2026-08-09. Until now playback was hardcoded to autoplay+loop in the storefront,
    # so a long film could not be offered without every visitor downloading it. LOOP is
    # the default because it is what every existing banner already does — the migration
    # must not change how the live homepage behaves.
    LOOP = "loop"
    CLICK = "click"
    VIDEO_MODE_CHOICES = [(LOOP, "Loop silently"), (CLICK, "Play on click")]
    video_mode = models.CharField(max_length=5, choices=VIDEO_MODE_CHOICES, default=LOOP)
```

- [ ] **Step 4: Generate the migration**

Run: `cd backend; uv run python manage.py makemigrations cms -n banner_video_mode`

Open the generated file and confirm it contains exactly one `AddField` with `default='loop'` and no other operations. If `makemigrations` wants unrelated changes, stop and investigate rather than accepting them.

- [ ] **Step 5: Expose it on both serializers**

`backend/apps/cms/serializers.py` — add `"video_mode"` to `PublicBannerSerializer.Meta.fields`:

```python
        fields = [
            "id", "title", "subtitle", "image", "mobile_image",
            "cta_text", "cta_url", "video_url", "video_mode", "tagline",
            "placement", "sort",
        ]
```

`backend/apps/cms/admin_serializers.py` — in `BannerAdminSerializer`, add `"video_mode"` to `Meta.fields` and to `audit_allowlist`. Playback mode is a campaign-visible decision, and that serializer's docstring says every such field is audited.

- [ ] **Step 6: Run tests**

Run: `cd backend; uv run pytest apps/cms -v`
Expected: PASS, including the two new tests.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/cms/models.py backend/apps/cms/migrations/ backend/apps/cms/serializers.py backend/apps/cms/admin_serializers.py backend/apps/cms/tests/test_landing_redesign.py
git commit -m "feat(cms): banners choose whether their video loops or waits for a click"
```

---

### Task 2: Video container sniffing

Pure functions over bytes. No S3, no Django — so the security-critical logic is testable in isolation and fast.

**Files:**
- Create: `backend/apps/cms/video_sniff.py`
- Test: `backend/apps/cms/tests/test_video_sniff.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `sniff_video_container(head: bytes) -> str | None` — returns `"mp4"`, `"webm"`, or `None`
  - `VIDEO_CONTENT_TYPES: dict[str, str]` — `{"mp4": "video/mp4", "webm": "video/webm"}`
  - `VIDEO_EXTENSIONS: dict[str, str]` — `{"mp4": ".mp4", "webm": ".webm"}`
  - `is_faststart(head: bytes) -> bool`

- [ ] **Step 1: Write the failing test**

Create `backend/apps/cms/tests/test_video_sniff.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; uv run pytest apps/cms/tests/test_video_sniff.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.cms.video_sniff'`.

- [ ] **Step 3: Implement**

Create `backend/apps/cms/video_sniff.py`:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `cd backend; uv run pytest apps/cms/tests/test_video_sniff.py -v`
Expected: PASS (10 cases).

- [ ] **Step 5: Commit**

```bash
git add backend/apps/cms/video_sniff.py backend/apps/cms/tests/test_video_sniff.py
git commit -m "feat(cms): identify video containers by their bytes, not their filename"
```

---

### Task 3: The S3 chokepoint — keys and guards

The prefix guard lands before anything can call S3, so no later task can add an unguarded delete.

**Files:**
- Create: `backend/apps/cms/s3_uploads.py`
- Test: `backend/apps/cms/tests/test_s3_uploads.py`
- Modify: `backend/apps/cms/admin_serializers.py:13` (raise `MAX_VIDEO_BYTES`)

**Interfaces:**
- Consumes: `apps.cms.video_sniff.VIDEO_EXTENSIONS`
- Produces:
  - `INCOMING_PREFIX = "incoming/"`, `LIBRARY_PREFIX = "catalog/library/"`
  - `class UnsafeKeyError(ValueError)`
  - `assert_incoming(key: str) -> str` — returns the key, raises `UnsafeKeyError` otherwise
  - `new_incoming_key(container: str) -> str` — `incoming/<uuid4>.<ext>`
  - `library_key_for(incoming_key: str) -> str` — deterministic destination

- [ ] **Step 1: Write the failing test**

Create `backend/apps/cms/tests/test_s3_uploads.py`:

```python
"""The guard tests are adversarial on purpose.

`infra/deploy/backup.sh` documents that the Django container holds the credential that
writes `backups/` — the only off-box copies of the database. Every delete and copy-source
in this feature goes through `assert_incoming`, so these cases are the seatbelt.
"""
import pytest

from apps.cms.s3_uploads import (
    INCOMING_PREFIX, LIBRARY_PREFIX, UnsafeKeyError,
    assert_incoming, library_key_for, new_incoming_key,
)


@pytest.mark.parametrize(
    "key",
    [
        "backups/postgres/toke-20260810-023001.sql.gz",
        "backups/",
        "catalog/library/existing.mp4",
        "catalog/cms-banners/hero.jpg",
        "incoming/../backups/steal.sql.gz",
        "incoming/../../etc/passwd",
        "/incoming/abc.mp4",
        "Incoming/abc.mp4",
        "",
        "   ",
    ],
)
def test_assert_incoming_refuses_anything_outside_the_quarantine(key):
    with pytest.raises(UnsafeKeyError):
        assert_incoming(key)


def test_assert_incoming_refuses_none():
    with pytest.raises(UnsafeKeyError):
        assert_incoming(None)  # type: ignore[arg-type]


def test_assert_incoming_allows_a_minted_key():
    key = new_incoming_key("mp4")
    assert assert_incoming(key) == key


def test_new_incoming_key_shape():
    key = new_incoming_key("mp4")
    assert key.startswith(INCOMING_PREFIX) and key.endswith(".mp4")
    # No client string anywhere in it: uuid4 hex + extension only.
    stem = key[len(INCOMING_PREFIX):-len(".mp4")]
    assert len(stem) == 32 and all(c in "0123456789abcdef" for c in stem)
    assert new_incoming_key("mp4") != key  # unique per call


def test_new_incoming_key_refuses_unknown_containers():
    with pytest.raises(UnsafeKeyError):
        new_incoming_key("mov")
    with pytest.raises(UnsafeKeyError):
        new_incoming_key("../../evil")


def test_library_key_is_deterministic():
    """Finalize must be idempotent, which means the destination cannot be random."""
    key = new_incoming_key("webm")
    assert library_key_for(key) == library_key_for(key)
    assert library_key_for(key).startswith(LIBRARY_PREFIX)
    assert library_key_for(key).endswith(".webm")


def test_library_key_refuses_a_non_incoming_source():
    with pytest.raises(UnsafeKeyError):
        library_key_for("backups/postgres/dump.sql.gz")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; uv run pytest apps/cms/tests/test_s3_uploads.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.cms.s3_uploads'`.

- [ ] **Step 3: Implement the guards**

Create `backend/apps/cms/s3_uploads.py`:

```python
"""Direct-to-S3 video uploads: the ONLY module in this feature that talks to S3.

WHY IT IS ONE MODULE. The bucket holds `backups/postgres/` — the only off-box copies of
the database — and `infra/deploy/backup.sh` documents that the `web` container carries
the credential that writes them. So application code that can call `delete_object` can
delete a database dump. Rather than trust every future call site to check its key, every
delete and every copy-source in this feature passes through `assert_incoming` here.

THE FLOW. `new_incoming_key` mints a key the client never influences; the presigned POST
pins it exactly (not `starts-with`) and bounds the size; the browser uploads to
`incoming/`, which the bucket policy does NOT expose to CloudFront; finalize sniffs the
real bytes and only then copies into `catalog/library/`, where the CDN can see it.
"""
import uuid

from apps.cms.video_sniff import VIDEO_EXTENSIONS

INCOMING_PREFIX = "incoming/"
LIBRARY_PREFIX = "catalog/library/"


class UnsafeKeyError(ValueError):
    """A key that is not inside the quarantine prefix. Never catch this to continue."""


def assert_incoming(key: str) -> str:
    """The seatbelt. Returns the key so callers can write `head(assert_incoming(k))`.

    Rejects traversal (`..`) explicitly: S3 keys are opaque strings and `incoming/../x`
    is a perfectly valid key naming a DIFFERENT object, so prefix-matching alone is not
    enough.
    """
    if not isinstance(key, str) or not key.strip():
        raise UnsafeKeyError("An empty key is never valid.")
    if not key.startswith(INCOMING_PREFIX):
        raise UnsafeKeyError(f"Refusing to touch a key outside {INCOMING_PREFIX!r}: {key!r}")
    if ".." in key:
        raise UnsafeKeyError(f"Refusing a key containing traversal: {key!r}")
    return key


def new_incoming_key(container: str) -> str:
    """`incoming/<uuid4hex>.<ext>` — no part of it comes from the client.

    The extension is looked up from the sniffed/declared CONTAINER, never sliced off a
    filename, so an attacker-chosen suffix cannot ride along inside a key we describe as
    server-generated.
    """
    try:
        ext = VIDEO_EXTENSIONS[container]
    except KeyError:
        raise UnsafeKeyError(f"Not a supported video container: {container!r}") from None
    return f"{INCOMING_PREFIX}{uuid.uuid4().hex}{ext}"


def library_key_for(incoming_key: str) -> str:
    """Where a verified object lands. DETERMINISTIC so finalize is idempotent: calling it
    twice copies to the same key and `get_or_create` finds the same row."""
    assert_incoming(incoming_key)
    return LIBRARY_PREFIX + incoming_key[len(INCOMING_PREFIX):]
```

- [ ] **Step 4: Run tests**

Run: `cd backend; uv run pytest apps/cms/tests/test_s3_uploads.py -v`
Expected: PASS (16 cases).

- [ ] **Step 5: Raise the video ceiling**

In `backend/apps/cms/admin_serializers.py`, replace line 13:

```python
MAX_VIDEO_BYTES = 80 * 1024 * 1024
```

with:

```python
# 128MB since 2026-08-09. The presigned path reads this for its S3 policy condition and
# again when re-checking what actually landed; the legacy multipart path still reads it
# too. ONE constant — a second copy is how `next.config.ts`'s unreachable 85MB ended up
# looking authoritative.
MAX_VIDEO_BYTES = 128 * 1024 * 1024
```

- [ ] **Step 6: Run the whole cms suite**

Run: `cd backend; uv run pytest apps/cms -v`
Expected: PASS. If a test asserted the old 80 MB message text, update it to read the constant rather than hardcoding a number.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/cms/s3_uploads.py backend/apps/cms/tests/test_s3_uploads.py backend/apps/cms/admin_serializers.py
git commit -m "feat(cms): quarantine-prefix guard for every S3 write this feature makes"
```

---

### Task 4: Presigned POST, head, ranged read

**Files:**
- Modify: `backend/apps/cms/s3_uploads.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/apps/cms/tests/test_s3_uploads.py`

**Interfaces:**
- Consumes: Task 3's guards; `apps.cms.admin_serializers.MAX_VIDEO_BYTES`
- Produces:
  - `mint_video_post(key: str, max_bytes: int) -> dict` — `{"url": str, "fields": dict, "key": str}`
  - `head_incoming(key: str) -> tuple[int, str]` — `(size_bytes, etag)`
  - `read_incoming_head(key: str, length: int = 262144) -> bytes`

- [ ] **Step 1: Add moto**

In `backend/pyproject.toml`, add to the dev dependency group alongside `pytest`:

```toml
    "moto[s3]>=5.0",
```

Run: `cd backend; uv sync`

- [ ] **Step 2: Write the failing test**

Append to `backend/apps/cms/tests/test_s3_uploads.py`:

```python
import boto3
import pytest
from moto import mock_aws

from apps.cms.s3_uploads import (
    head_incoming, mint_video_post, new_incoming_key, read_incoming_head,
)

BUCKET = "test-bucket"


@pytest.fixture
def s3(settings):
    """A live-enough S3. `settings` is pytest-django's fixture."""
    settings.AWS_STORAGE_BUCKET_NAME = BUCKET
    settings.AWS_S3_REGION_NAME = "eu-west-1"
    with mock_aws():
        client = boto3.client("s3", region_name="eu-west-1")
        client.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "eu-west-1"},
        )
        yield client


def test_mint_video_post_pins_the_key_exactly_and_bounds_the_size(s3):
    key = new_incoming_key("mp4")
    ticket = mint_video_post(key, max_bytes=1000)

    assert ticket["key"] == key
    # The key travels as a FIELD, which S3 matches exactly — not a starts-with condition.
    assert ticket["fields"]["key"] == key
    conditions = ticket["_conditions"]
    assert ["content-length-range", 1, 1000] in conditions
    assert not any(
        isinstance(c, list) and c and c[0] == "starts-with" and c[1] == "$key"
        for c in conditions
    ), "a starts-with key condition would let the client choose where bytes land"


def test_head_incoming_returns_real_size_and_etag(s3):
    key = new_incoming_key("mp4")
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"x" * 1234)

    size, etag = head_incoming(key)
    assert size == 1234
    assert etag and '"' not in etag  # normalised, ready for CopySourceIfMatch


def test_read_incoming_head_reads_only_the_front(s3):
    key = new_incoming_key("mp4")
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"HEAD" + b"z" * 500_000)

    head = read_incoming_head(key, length=16)
    assert head.startswith(b"HEAD")
    assert len(head) == 16, "a ranged read must not pull the whole object"


def test_every_s3_helper_refuses_a_backups_key(s3):
    for fn in (head_incoming, read_incoming_head):
        with pytest.raises(UnsafeKeyError):
            fn("backups/postgres/dump.sql.gz")
    with pytest.raises(UnsafeKeyError):
        mint_video_post("backups/postgres/dump.sql.gz", max_bytes=10)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend; uv run pytest apps/cms/tests/test_s3_uploads.py -v`
Expected: FAIL — `ImportError: cannot import name 'mint_video_post'`.

- [ ] **Step 4: Implement**

Append to `backend/apps/cms/s3_uploads.py` (and add `import boto3` / `from django.conf import settings` at the top):

```python
# Ticket lifetime. Generous on purpose: the key is pinned into a prefix the CDN cannot
# serve, so a long window costs nothing, while a short one punishes an admin who picks a
# file and takes a phone call.
TICKET_TTL_SECONDS = 30 * 60
# How much of the object finalize reads to identify it. Large enough for any container
# header and the moov/mdat question; small enough to be one quick ranged GET.
SNIFF_BYTES = 262_144


def _client():
    return boto3.client("s3", region_name=settings.AWS_S3_REGION_NAME)


def _bucket() -> str:
    return settings.AWS_STORAGE_BUCKET_NAME


def mint_video_post(key: str, max_bytes: int) -> dict:
    """A one-shot S3 POST form for exactly `key`, refusing anything over `max_bytes`.

    Presigned POST rather than PUT specifically for `content-length-range`: a presigned
    PUT can pin the key but cannot bound the body, and this bucket holds the database
    backups — an unbounded write into it is not a risk worth taking for a simpler call.
    """
    assert_incoming(key)
    conditions: list = [
        {"key": key},                          # EXACT match, never starts-with
        ["content-length-range", 1, max_bytes],
    ]
    post = _client().generate_presigned_post(
        Bucket=_bucket(),
        Key=key,
        Fields={"key": key},
        Conditions=conditions,
        ExpiresIn=TICKET_TTL_SECONDS,
    )
    # `_conditions` is echoed back for the tests that pin the policy shape; it is not
    # sent to the browser (the serializer picks the fields it exposes).
    return {"url": post["url"], "fields": post["fields"], "key": key, "_conditions": conditions}


def head_incoming(key: str) -> tuple[int, str]:
    """(size, etag) of what ACTUALLY landed. The ticket's claimed size is not evidence."""
    assert_incoming(key)
    meta = _client().head_object(Bucket=_bucket(), Key=key)
    return int(meta["ContentLength"]), meta["ETag"].strip('"')


def read_incoming_head(key: str, length: int = SNIFF_BYTES) -> bytes:
    """The first `length` bytes, via a ranged GET — never the whole object."""
    assert_incoming(key)
    obj = _client().get_object(Bucket=_bucket(), Key=key, Range=f"bytes=0-{length - 1}")
    return obj["Body"].read()
```

- [ ] **Step 5: Run tests**

Run: `cd backend; uv run pytest apps/cms/tests/test_s3_uploads.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/apps/cms/s3_uploads.py backend/apps/cms/tests/test_s3_uploads.py
git commit -m "feat(cms): presigned POST tickets with an exact key and a size bound"
```

---

### Task 5: Publish and discard

The copy is the commit point. `CopySourceIfMatch` is what makes "the bytes we sniffed" and "the bytes we published" provably the same object.

**Files:**
- Modify: `backend/apps/cms/s3_uploads.py`
- Test: `backend/apps/cms/tests/test_s3_uploads.py`

**Interfaces:**
- Consumes: Task 3 + Task 4
- Produces:
  - `publish_incoming(key: str, etag: str, content_type: str) -> str` — returns the library key
  - `discard_incoming(key: str) -> None` — never raises on a missing object

- [ ] **Step 1: Write the failing test**

Append to `backend/apps/cms/tests/test_s3_uploads.py`:

```python
from unittest.mock import patch

from apps.cms.s3_uploads import discard_incoming, library_key_for, publish_incoming


def test_publish_copies_into_the_library_and_sets_our_own_content_type(s3):
    key = new_incoming_key("mp4")
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"\x00\x00\x00\x20ftypisom",
                  ContentType="text/html")  # the client lied
    _, etag = head_incoming(key)

    dest = publish_incoming(key, etag=etag, content_type="video/mp4")

    assert dest == library_key_for(key)
    landed = s3.head_object(Bucket=BUCKET, Key=dest)
    assert landed["ContentType"] == "video/mp4", "the client's Content-Type must not survive"
    assert "immutable" in landed["CacheControl"]


def test_publish_is_idempotent(s3):
    key = new_incoming_key("mp4")
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"\x00\x00\x00\x20ftypisom")
    _, etag = head_incoming(key)

    first = publish_incoming(key, etag=etag, content_type="video/mp4")
    second = publish_incoming(key, etag=etag, content_type="video/mp4")
    assert first == second


def test_publish_sends_the_safety_kwargs():
    """Asserted on the CALL, not through moto: the TOCTOU defence must not rest on how
    faithfully a simulator implements conditional copy."""
    key = new_incoming_key("mp4")
    with patch("apps.cms.s3_uploads._client") as client:
        publish_incoming(key, etag="abc123", content_type="video/mp4")
        kwargs = client.return_value.copy_object.call_args.kwargs

    assert kwargs["CopySourceIfMatch"] == "abc123"
    assert kwargs["MetadataDirective"] == "REPLACE"
    assert kwargs["ContentType"] == "video/mp4"
    assert kwargs["Key"] == library_key_for(key)


def test_publish_refuses_a_source_outside_the_quarantine():
    with pytest.raises(UnsafeKeyError):
        publish_incoming("backups/postgres/dump.sql.gz", etag="x", content_type="video/mp4")


def test_discard_refuses_a_backups_key():
    with pytest.raises(UnsafeKeyError):
        discard_incoming("backups/postgres/dump.sql.gz")


def test_discard_survives_an_already_gone_object(s3):
    """Finalize's cleanup must never turn a successful publish into a failed request."""
    discard_incoming(new_incoming_key("mp4"))  # never uploaded; must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; uv run pytest apps/cms/tests/test_s3_uploads.py -k "publish or discard" -v`
Expected: FAIL — `ImportError: cannot import name 'publish_incoming'`.

- [ ] **Step 3: Implement**

Append to `backend/apps/cms/s3_uploads.py`:

```python
# Keys are unique forever, so the object at one is immutable by construction.
PUBLISHED_CACHE_CONTROL = "public, max-age=31536000, immutable"


def publish_incoming(key: str, etag: str, content_type: str) -> str:
    """Copy a VERIFIED object into the library prefix. Returns the destination key.

    `CopySourceIfMatch` is the load-bearing argument: the presigned ticket stays valid
    while finalize runs, so without it a holder could replace the bytes between the sniff
    and the copy and publish something we never inspected. With it the copy fails
    atomically instead.

    `MetadataDirective="REPLACE"` is equally load-bearing and easy to omit: without it S3
    copies the SOURCE's metadata, including the Content-Type the client chose — which
    would hand back exactly the "served as active content" problem the sniff exists to
    prevent.
    """
    assert_incoming(key)
    dest = library_key_for(key)
    _client().copy_object(
        Bucket=_bucket(),
        Key=dest,
        CopySource={"Bucket": _bucket(), "Key": key},
        CopySourceIfMatch=etag,
        MetadataDirective="REPLACE",
        ContentType=content_type,
        CacheControl=PUBLISHED_CACHE_CONTROL,
    )
    return dest


def discard_incoming(key: str) -> None:
    """Best-effort cleanup of a quarantined object.

    Never raises for a missing object, and callers must not let a failure here fail the
    request: once the copy has succeeded the upload HAS worked, and the lifecycle rule on
    `incoming/` reclaims anything left behind.
    """
    assert_incoming(key)
    try:
        _client().delete_object(Bucket=_bucket(), Key=key)
    except Exception:  # noqa: BLE001 - cleanup must never mask a successful publish
        pass
```

- [ ] **Step 4: Run tests**

Run: `cd backend; uv run pytest apps/cms/tests/test_s3_uploads.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/apps/cms/s3_uploads.py backend/apps/cms/tests/test_s3_uploads.py
git commit -m "feat(cms): publish verified uploads with the sniffed type welded to the bytes"
```

---

### Task 6: The two API endpoints

**Files:**
- Modify: `backend/apps/cms/admin_serializers.py`
- Modify: `backend/apps/cms/admin_views.py:72-97`
- Test: `backend/apps/cms/tests/test_video_upload_api.py`

**Interfaces:**
- Consumes: everything from Tasks 2–5
- Produces:
  - `POST /api/v1/admin/cms/media/video-ticket/` — body `{"filename": str, "size": int, "container": "mp4"|"webm"}` → `{"url", "fields", "key"}`
  - `POST /api/v1/admin/cms/media/video-finalize/` — body `{"key": str, "original_name": str}` → a `MediaAsset` row, plus `"warning"` when the file is not faststart

- [ ] **Step 1: Write the failing test**

Create `backend/apps/cms/tests/test_video_upload_api.py`. Copy the admin-authentication fixture pattern from `backend/apps/cms/tests/test_media_library.py` — read that file first and reuse its client fixture verbatim rather than inventing a second way to authenticate.

```python
"""End-to-end for the presigned video path. See
docs/superpowers/specs/2026-08-09-presigned-video-uploads-design.md."""
import boto3
import pytest
from moto import mock_aws

from apps.cms.models import MediaAsset
from apps.cms.s3_uploads import LIBRARY_PREFIX, library_key_for, new_incoming_key

BUCKET = "test-bucket"
MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00\x00\x01\x00moov" + b"\x00" * 2048
TICKET = "/api/v1/admin/cms/media/video-ticket/"
FINALIZE = "/api/v1/admin/cms/media/video-finalize/"


@pytest.fixture
def s3(settings):
    settings.AWS_STORAGE_BUCKET_NAME = BUCKET
    settings.AWS_S3_REGION_NAME = "eu-west-1"
    with mock_aws():
        c = boto3.client("s3", region_name="eu-west-1")
        c.create_bucket(Bucket=BUCKET,
                        CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
        yield c


@pytest.mark.django_db
def test_ticket_then_finalize_publishes_one_asset(client, s3):
    r = client.post(TICKET, {"filename": "hero.mp4", "size": len(MP4), "container": "mp4"},
                    format="json")
    assert r.status_code == 200
    key = r.json()["key"]
    assert key.startswith("incoming/")

    s3.put_object(Bucket=BUCKET, Key=key, Body=MP4)  # stands in for the browser's POST

    r = client.post(FINALIZE, {"key": key, "original_name": "hero.mp4"}, format="json")
    assert r.status_code == 201, r.json()
    asset = MediaAsset.objects.get()
    assert asset.kind == MediaAsset.VIDEO
    assert asset.file.name == library_key_for(key)
    assert asset.original_name == "hero.mp4"
    assert asset.size == len(MP4)
    # The quarantine copy is gone and the library copy exists.
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET, Prefix="incoming/")
    assert s3.head_object(Bucket=BUCKET, Key=library_key_for(key))


@pytest.mark.django_db
def test_finalize_twice_yields_one_row(client, s3):
    r = client.post(TICKET, {"filename": "a.mp4", "size": len(MP4), "container": "mp4"},
                    format="json")
    key = r.json()["key"]
    s3.put_object(Bucket=BUCKET, Key=key, Body=MP4)

    first = client.post(FINALIZE, {"key": key, "original_name": "a.mp4"}, format="json")
    second = client.post(FINALIZE, {"key": key, "original_name": "a.mp4"}, format="json")

    assert first.status_code == 201
    assert second.status_code in (200, 201)
    assert MediaAsset.objects.count() == 1


@pytest.mark.django_db
def test_ticket_refuses_a_size_over_the_ceiling(client, s3):
    from apps.cms.admin_serializers import MAX_VIDEO_BYTES

    r = client.post(TICKET, {"filename": "huge.mp4", "size": MAX_VIDEO_BYTES + 1,
                             "container": "mp4"}, format="json")
    assert r.status_code == 400
    assert "128" in str(r.json())


@pytest.mark.django_db
def test_finalize_rechecks_the_real_size_even_when_the_ticket_lied(client, s3, settings):
    settings.CMS_TEST_TINY_CAP = True
    r = client.post(TICKET, {"filename": "a.mp4", "size": 10, "container": "mp4"},
                    format="json")
    key = r.json()["key"]
    # Bypass the browser and the policy entirely — put far more than was declared.
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"\x00\x00\x00\x20ftyp" + b"z" * 200)

    from apps.cms import admin_serializers
    monkey_cap = 100
    original = admin_serializers.MAX_VIDEO_BYTES
    admin_serializers.MAX_VIDEO_BYTES = monkey_cap
    try:
        r = client.post(FINALIZE, {"key": key, "original_name": "a.mp4"}, format="json")
    finally:
        admin_serializers.MAX_VIDEO_BYTES = original

    assert r.status_code == 400
    assert MediaAsset.objects.count() == 0


@pytest.mark.django_db
def test_finalize_rejects_a_png_wearing_an_mp4_key(client, s3):
    r = client.post(TICKET, {"filename": "sneaky.mp4", "size": 100, "container": "mp4"},
                    format="json")
    key = r.json()["key"]
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    r = client.post(FINALIZE, {"key": key, "original_name": "sneaky.mp4"}, format="json")

    assert r.status_code == 400
    assert "video" in str(r.json()).lower()
    assert MediaAsset.objects.count() == 0
    # Rejected bytes are removed, not left sitting in the bucket.
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET, Prefix="incoming/")


@pytest.mark.django_db
def test_finalize_refuses_a_key_outside_the_quarantine(client, s3):
    r = client.post(FINALIZE, {"key": "backups/postgres/dump.sql.gz",
                               "original_name": "x"}, format="json")
    assert r.status_code == 400
    assert MediaAsset.objects.count() == 0


@pytest.mark.django_db
def test_non_faststart_file_is_accepted_with_a_warning(client, s3):
    slow = b"\x00\x00\x00\x20ftypisom" + b"\x00\x00\x01\x00mdat" + b"\x00" * 512
    r = client.post(TICKET, {"filename": "slow.mp4", "size": len(slow), "container": "mp4"},
                    format="json")
    key = r.json()["key"]
    s3.put_object(Bucket=BUCKET, Key=key, Body=slow)

    r = client.post(FINALIZE, {"key": key, "original_name": "slow.mp4"}, format="json")
    assert r.status_code == 201
    assert "faststart" in r.json()["warning"].lower()
```

Add a permissions test mirroring however `test_media_library.py` asserts scope refusal — both endpoints must 403 without `marketing.manage`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend; uv run pytest apps/cms/tests/test_video_upload_api.py -v`
Expected: FAIL — 404 on both routes.

- [ ] **Step 3: Add the serializers**

Append to `backend/apps/cms/admin_serializers.py`:

```python
class VideoTicketRequestSerializer(serializers.Serializer):
    """What the browser asks for. Note what is NOT here: the destination key. The client
    does not get to influence where its bytes land."""

    audit_allowlist = ("filename", "size", "container")

    filename = serializers.CharField(max_length=255)
    size = serializers.IntegerField(min_value=1)
    container = serializers.ChoiceField(choices=["mp4", "webm"])

    def validate_size(self, size):
        if size > MAX_VIDEO_BYTES:
            raise serializers.ValidationError(
                f"Keep videos under {MAX_VIDEO_BYTES // (1024 * 1024)} MB — "
                "re-encode at 720p and about 2 Mbps, which is plenty for the web."
            )
        return size


class VideoFinalizeSerializer(serializers.Serializer):
    """`key` is echoed back from the ticket. It is re-validated server-side rather than
    trusted — see `s3_uploads.assert_incoming`."""

    audit_allowlist = ("key", "original_name")

    key = serializers.CharField(max_length=300)
    original_name = serializers.CharField(max_length=255, allow_blank=True, default="")
```

- [ ] **Step 4: Add the endpoints**

In `backend/apps/cms/admin_views.py`, extend `MediaAssetAdminViewSet`. Add imports at the top: `from rest_framework.decorators import action`, `from rest_framework.response import Response`, `from apps.cms import s3_uploads`, `from apps.cms.video_sniff import VIDEO_CONTENT_TYPES, is_faststart, sniff_video_container`, and the two new serializers.

Extend the class attribute so the audit guard sees the real body shapes:

```python
    audit_serializers = (
        MediaAssetAdminSerializer, VideoTicketRequestSerializer, VideoFinalizeSerializer,
    )
```

Then add:

```python
    @action(detail=False, methods=["post"], url_path="video-ticket")
    def video_ticket(self, request):
        """Mint a one-shot S3 POST form. The bytes bypass this server entirely.

        WHY THIS EXISTS: Vercel rejects function request bodies over ~4.5MB at its edge
        before Next runs (measured 2026-08-09: 3.91MB passes, 4.30MB 413s), so a video
        relayed through the admin's server actions cannot arrive. Images still take the
        old path — they are downscaled under 4MB in the browser and their full-byte
        Pillow check is worth keeping.
        """
        body = VideoTicketRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        key = s3_uploads.new_incoming_key(body.validated_data["container"])
        ticket = s3_uploads.mint_video_post(key, max_bytes=MAX_VIDEO_BYTES)
        return Response({"url": ticket["url"], "fields": ticket["fields"], "key": key})

    @action(detail=False, methods=["post"], url_path="video-finalize")
    def video_finalize(self, request):
        """Verify what landed, publish it, and record the asset.

        Order matters: copy BEFORE the row is written. The inverse would leave a row
        pointing at nothing, which a banner could then attach to.
        """
        body = VideoFinalizeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        key = body.validated_data["key"]

        try:
            s3_uploads.assert_incoming(key)
        except s3_uploads.UnsafeKeyError:
            raise serializers.ValidationError({"key": "That upload key is not valid."}) from None

        size, etag = s3_uploads.head_incoming(key)
        if size > MAX_VIDEO_BYTES:
            s3_uploads.discard_incoming(key)
            raise serializers.ValidationError(
                {"key": f"That video is {size // (1024 * 1024)} MB — the limit is "
                        f"{MAX_VIDEO_BYTES // (1024 * 1024)} MB."}
            )

        head = s3_uploads.read_incoming_head(key)
        container = sniff_video_container(head)
        if container is None:
            s3_uploads.discard_incoming(key)
            raise serializers.ValidationError(
                {"key": "That file isn't an mp4 or webm video."}
            )

        dest = s3_uploads.publish_incoming(
            key, etag=etag, content_type=VIDEO_CONTENT_TYPES[container],
        )
        asset, created = MediaAsset.objects.get_or_create(
            file=dest,
            defaults={
                "kind": MediaAsset.VIDEO,
                "original_name": body.validated_data["original_name"][:255],
                "size": size,
                "uploaded_by": request.user,
            },
        )
        s3_uploads.discard_incoming(key)

        payload = MediaAssetAdminSerializer(asset).data
        if not is_faststart(head):
            payload["warning"] = (
                "This video is not faststart-encoded, so browsers must download all of "
                "it before playing. Re-encode with ffmpeg's -movflags +faststart."
            )
        return Response(payload, status=201 if created else 200)
```

- [ ] **Step 5: Run tests**

Run: `cd backend; uv run pytest apps/cms -v`
Expected: PASS. Also run the guard suites, which assert every admin view is audited and scoped:

Run: `cd backend; uv run pytest apps/core -k "audit_guard or surface_guard" -v`
Expected: PASS. If the surface guard complains about the new actions, follow its message — do not weaken the guard.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/cms/admin_serializers.py backend/apps/cms/admin_views.py backend/apps/cms/tests/test_video_upload_api.py
git commit -m "feat(cms): video ticket and finalize endpoints"
```

---

### Task 7: The browser's upload helper

**Files:**
- Create: `admin/src/lib/video.ts`
- Create: `admin/src/lib/upload.ts`
- Create: `admin/src/lib/__tests__/upload.test.ts`
- Modify: `admin/src/lib/csp.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure browser code)
- Produces:
  - `VIDEO_CAP_BYTES = 128_000_000`, `LOOP_WARN_BYTES = 6_000_000` from `@/lib/video`
  - `interface UploadTicket { url: string; fields: Record<string, string>; key: string }`
  - `uploadToS3(ticket, file, onProgress): { promise: Promise<void>; abort: () => void }`

- [ ] **Step 1: Write the failing test**

Create `admin/src/lib/__tests__/upload.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { uploadToS3 } from "@/lib/upload";

class FakeXHR {
  static last: FakeXHR;
  upload = { onprogress: null as null | ((e: ProgressEvent) => void) };
  onload: null | (() => void) = null;
  onerror: null | (() => void) = null;
  onabort: null | (() => void) = null;
  status = 204;
  responseText = "";
  sent: FormData | null = null;
  aborted = false;
  constructor() { FakeXHR.last = this; }
  open() {}
  send(body: FormData) { this.sent = body; }
  abort() { this.aborted = true; this.onabort?.(); }
}

beforeEach(() => { vi.stubGlobal("XMLHttpRequest", FakeXHR); });
afterEach(() => { vi.unstubAllGlobals(); });

const ticket = { url: "https://s3.example/bucket", fields: { key: "incoming/a.mp4", policy: "p" }, key: "incoming/a.mp4" };
const file = new File(["xyz"], "a.mp4", { type: "video/mp4" });

describe("uploadToS3", () => {
  it("posts every policy field before the file, which S3 requires", async () => {
    const handle = uploadToS3(ticket, file, () => {});
    FakeXHR.last.onload!();
    await handle.promise;

    const keys = [...(FakeXHR.last.sent as FormData).keys()];
    expect(keys).toEqual(["key", "policy", "file"]);
  });

  it("reports progress as a percentage", async () => {
    const seen: number[] = [];
    const handle = uploadToS3(ticket, file, (pct) => seen.push(pct));
    FakeXHR.last.upload.onprogress!({ lengthComputable: true, loaded: 25, total: 100 } as ProgressEvent);
    FakeXHR.last.upload.onprogress!({ lengthComputable: true, loaded: 100, total: 100 } as ProgressEvent);
    FakeXHR.last.onload!();
    await handle.promise;

    expect(seen).toEqual([25, 100]);
  });

  it("rejects with S3's status when the policy is refused", async () => {
    const handle = uploadToS3(ticket, file, () => {});
    FakeXHR.last.status = 403;
    FakeXHR.last.responseText = "<Error><Code>EntityTooLarge</Code></Error>";
    FakeXHR.last.onload!();

    await expect(handle.promise).rejects.toThrow(/EntityTooLarge/);
  });

  it("rejects on a network drop rather than hanging forever", async () => {
    const handle = uploadToS3(ticket, file, () => {});
    FakeXHR.last.onerror!();
    await expect(handle.promise).rejects.toThrow(/connection/i);
  });

  it("can be aborted", async () => {
    const handle = uploadToS3(ticket, file, () => {});
    handle.abort();
    await expect(handle.promise).rejects.toThrow(/cancelled/i);
    expect(FakeXHR.last.aborted).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd admin; npm test -- --run src/lib/__tests__/upload.test.ts`
Expected: FAIL — cannot resolve `@/lib/upload`.

*(If the suite cannot start at all with `Cannot find module @rollup/rollup-win32-x64-msvc`, run `npm i @rollup/rollup-win32-x64-msvc --no-save` — a known npm optional-dependency bug on this machine, not a code problem.)*

- [ ] **Step 3: Implement**

Create `admin/src/lib/video.ts`:

```ts
/** Video upload limits.
 *
 * The 128MB ceiling mirrors the API's `MAX_VIDEO_BYTES` and is a guardrail, not a target:
 * a 3-minute film at 720p/~2Mbps lands around 45-55MB. Videos bypass Vercel entirely
 * (see lib/upload.ts), so the ~4MB request cap in lib/image.ts does not apply to them.
 */
export const VIDEO_CAP_BYTES = 128_000_000;

/** Above this, a LOOPING video is worth warning about — it autoplays for every visitor,
 * many on mobile data. Click-to-play videos are opt-in and get no warning. */
export const LOOP_WARN_BYTES = 6_000_000;

export function fileSizeMb(file: { size: number }): string {
  return `${(file.size / 1_000_000).toFixed(1)} MB`;
}
```

Create `admin/src/lib/upload.ts`:

```ts
/** Browser -> S3 directly, bypassing Vercel (2026-08-09).
 *
 * WHY XHR AND NOT FETCH: `fetch` reports no upload progress. A 90MB video on a slow
 * uplink takes minutes, and a progress-less minute reads as "it has frozen" — this is an
 * admin surface where the alternative to a progress bar is a support message.
 *
 * WHY THE FIELD ORDER MATTERS: S3 evaluates a POST policy against the fields in the
 * order they arrive and IGNORES ANYTHING AFTER `file`. Appending the file last is not a
 * style choice; put it first and every upload is refused.
 */
import type { UploadTicket } from "@/lib/upload-types";

export type { UploadTicket };

export interface UploadHandle {
  promise: Promise<void>;
  abort: () => void;
}

export function uploadToS3(
  ticket: UploadTicket,
  file: File,
  onProgress: (percent: number) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest();
  const body = new FormData();
  for (const [k, v] of Object.entries(ticket.fields)) body.set(k, v);
  body.set("file", file);  // MUST be last — see the header comment.

  const promise = new Promise<void>((resolve, reject) => {
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      // S3 answers a successful POST with 204 (or 201 when success_action_status is set).
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      reject(new Error(s3Message(xhr.status, xhr.responseText)));
    };
    xhr.onerror = () => reject(new Error("The connection dropped during the upload."));
    xhr.onabort = () => reject(new Error("The upload was cancelled."));
    xhr.open("POST", ticket.url);
    xhr.send(body);
  });

  return { promise, abort: () => xhr.abort() };
}

/** S3 refuses with an XML body. Surfacing its <Code> beats a bare status number. */
function s3Message(status: number, responseText: string): string {
  const code = /<Code>([^<]+)<\/Code>/.exec(responseText)?.[1];
  if (code === "EntityTooLarge") return "EntityTooLarge: that file is over the size limit.";
  if (code === "AccessDenied" || code === "ExpiredToken") {
    return `${code}: the upload window expired. Choose the file again.`;
  }
  return code ? `${code} (HTTP ${status})` : `The upload failed (HTTP ${status}).`;
}
```

Create `admin/src/lib/upload-types.ts` (a separate module so the server actions can import
the type without pulling browser-only code into a server bundle):

```ts
/** The shape the API's video-ticket endpoint returns. */
export interface UploadTicket {
  url: string;
  fields: Record<string, string>;
  key: string;
}
```

- [ ] **Step 4: Run tests**

Run: `cd admin; npm test -- --run src/lib/__tests__/upload.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Allow the browser to reach S3**

In `admin/src/lib/csp.ts`, `connect-src` currently reads `["'self'", apiOrigin(), ...TURNSTILE]`. The browser now POSTs to S3, which that blocks. Add a helper beside the existing `mediaHost()` and include it:

```ts
/** The S3 endpoint the browser POSTs video straight to (2026-08-09). NOT the CloudFront
 * host: uploads go to the bucket, reads come back through the CDN. */
function uploadHost(): string {
  const bucket = process.env.NEXT_PUBLIC_UPLOAD_BUCKET_HOST;
  return bucket ? `https://${bucket}` : "";
}
```

and change the directive to `["'self'", apiOrigin(), uploadHost(), ...TURNSTILE].filter(Boolean)`.

Match however `mediaHost()` reads its env var; follow that pattern exactly rather than inventing a new convention. Set `NEXT_PUBLIC_UPLOAD_BUCKET_HOST=tokecosmetics-assets-899805259502-eu-west-1-an.s3.eu-west-1.amazonaws.com` in `admin/.env.local` and, at deploy time, in Vercel.

- [ ] **Step 6: Verify CSP tests still pass**

Run: `cd admin; npm test -- --run src/lib/__tests__ && npm run typecheck && npm run lint`
Expected: PASS. If a snapshot pins the CSP string, update it deliberately.

- [ ] **Step 7: Commit**

```bash
git add admin/src/lib/video.ts admin/src/lib/upload.ts admin/src/lib/upload-types.ts admin/src/lib/__tests__/upload.test.ts admin/src/lib/csp.ts
git commit -m "feat(admin): XHR upload straight to S3, with progress and cancel"
```

---

### Task 8: Server actions and the media library

**Files:**
- Modify: `admin/src/app/(shell)/content/media/actions.ts`
- Modify: `admin/src/components/content/MediaLibraryModal.tsx`
- Test: `admin/src/components/content/__tests__/MediaLibraryModal.test.tsx`

**Interfaces:**
- Consumes: Task 6's endpoints; Task 7's `uploadToS3`, `VIDEO_CAP_BYTES`
- Produces:
  - `requestVideoTicketAction(input: { filename: string; size: number; container: "mp4" | "webm" }): Promise<{ ticket?: UploadTicket; message?: string }>`
  - `finalizeVideoAction(input: { key: string; originalName: string }): Promise<{ asset?: MediaAssetRow; warning?: string; message?: string }>`

- [ ] **Step 1: Write the failing test**

Add to the MediaLibraryModal test file (create it if absent, following the structure of the existing modal tests in `admin/src/components/content/__tests__/`):

```tsx
it("refuses a video over the ceiling without contacting the server", async () => {
  const requestTicket = vi.fn();
  render(<MediaLibraryModal kind="video" onPick={() => {}} onClose={() => {}}
                            actions={{ requestVideoTicket: requestTicket }} />);

  const huge = new File(["x"], "film.mp4", { type: "video/mp4" });
  Object.defineProperty(huge, "size", { value: 200_000_000 });
  fireEvent.change(screen.getByLabelText(/upload/i), { target: { files: [huge] } });

  expect(await screen.findByRole("alert")).toHaveTextContent(/200\.0 MB/);
  expect(requestTicket).not.toHaveBeenCalled();
});

it("shows upload progress and finalizes on success", async () => {
  // ... drives the three-step flow with stubbed actions and asserts the progress text
  // then that finalize was called with the ticket's key.
});
```

Adapt the props to whatever `MediaLibraryModal` actually takes — read the component first. If it imports its server actions directly rather than receiving them, inject them via `vi.mock` of the actions module, matching how sibling tests do it.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd admin; npm test -- --run src/components/content/__tests__/MediaLibraryModal.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Add the server actions**

Append to `admin/src/app/(shell)/content/media/actions.ts`:

```ts
/** Video takes a different route from images (2026-08-09): the browser uploads straight
 * to S3 because Vercel rejects request bodies over ~4.5MB at its edge, before this
 * action would ever run. These two calls are small JSON either side of that upload. */
export async function requestVideoTicketAction(input: {
  filename: string;
  size: number;
  container: "mp4" | "webm";
}): Promise<{ ticket?: UploadTicket; message?: string }> {
  try {
    const ticket = await fetchWithAuth<UploadTicket>("/admin/cms/media/video-ticket/", {
      method: "POST",
      json: input,
    });
    return { ticket };
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    const data = e.data as Record<string, unknown> | undefined;
    const detail = Array.isArray(data?.size) ? data.size[0] : undefined;
    return { message: typeof detail === "string" ? detail : "Could not start the upload." };
  }
}

export async function finalizeVideoAction(input: {
  key: string;
  originalName: string;
}): Promise<{ asset?: MediaAssetRow; warning?: string; message?: string }> {
  try {
    const asset = await fetchWithAuth<MediaAssetRow & { warning?: string }>(
      "/admin/cms/media/video-finalize/",
      { method: "POST", json: { key: input.key, original_name: input.originalName } },
    );
    return { asset, warning: asset.warning };
  } catch (e) {
    if (!(e instanceof ApiError)) return { message: "The API is not responding." };
    const data = e.data as Record<string, unknown> | undefined;
    const detail = Array.isArray(data?.key) ? data.key[0] : undefined;
    return { message: typeof detail === "string" ? detail : "The upload could not be verified." };
  }
}
```

Match `fetchWithAuth`'s real option names — read `admin/src/lib/session.ts` and `admin/src/lib/api.ts` and use whatever the codebase uses for a JSON body (it may be `body: JSON.stringify(...)` with a header rather than a `json` option). Do not introduce a new convention.

- [ ] **Step 4: Wire the modal**

In `MediaLibraryModal.tsx`, replace the video branch of `stageFile`. Images keep calling `downscaleImage` + `uploadMediaAction` exactly as they do now.

```tsx
    if (kind === "video") {
      if (file.size > VIDEO_CAP_BYTES) {
        setMessage(
          `That video is ${fileSizeMb(file)} — the limit is 128 MB. Re-encode it at ` +
          `720p and about 2 Mbps (ffmpeg -crf 28 -movflags +faststart) and try again.`,
        );
        return;
      }
      const container = file.name.toLowerCase().endsWith(".webm") ? "webm" : "mp4";
      const { ticket, message } = await requestVideoTicketAction({
        filename: file.name, size: file.size, container,
      });
      if (!ticket) return setMessage(message ?? "Could not start the upload.");

      setProgress(0);
      const handle = uploadToS3(ticket, file, setProgress);
      abortRef.current = handle.abort;
      try {
        await handle.promise;
      } catch (e) {
        setProgress(null);
        // Large videos cannot resume; say so rather than implying a silent retry works.
        setMessage(`${(e as Error).message} Large videos can't resume — choose it again.`);
        return;
      } finally {
        abortRef.current = null;
      }
      setProgress(null);

      const done = await finalizeVideoAction({ key: ticket.key, originalName: file.name });
      if (!done.asset) return setMessage(done.message ?? "The upload could not be verified.");
      if (done.warning) setMessage(done.warning);
      onPick(done.asset);
      return;
    }
```

Add the `progress` and `abortRef` state, render a progress bar with a Cancel button while `progress !== null`, and import `VIDEO_CAP_BYTES`, `fileSizeMb` from `@/lib/video` and `uploadToS3` from `@/lib/upload`.

- [ ] **Step 5: Run tests**

Run: `cd admin; npm test -- --run && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add admin/src/app/\(shell\)/content/media/actions.ts admin/src/components/content/MediaLibraryModal.tsx admin/src/components/content/__tests__/
git commit -m "feat(admin): media library uploads video straight to S3"
```

---

### Task 9: The tile editor — video slot and mode

**Files:**
- Modify: `admin/src/components/content/HomeBannerModal.tsx`
- Modify: `admin/src/lib/banners.ts`
- Test: `admin/src/components/content/__tests__/HomeBannerModal.test.tsx`

**Interfaces:**
- Consumes: Tasks 7 and 8
- Produces: the modal saves `video_mode` with the banner and uploads video via the presigned path

- [ ] **Step 1: Write the failing test**

Add to the HomeBannerModal test file:

```tsx
it("keeps PATCHing after a failed video upload — never creates a second banner", async () => {
  // Regression guard for commit 8935354. The video slot is now three steps, which is
  // exactly where a careless edit could reintroduce the duplicate.
  const save = vi.fn().mockResolvedValue({ savedAt: 1, id: 42 });
  const finalize = vi.fn().mockResolvedValueOnce({ message: "verification failed" })
                          .mockResolvedValueOnce({ asset: { id: 7 } });
  renderModal({ banner: null, actions: { save, finalize } });

  await pickVideo(smallMp4());
  fireEvent.click(screen.getByRole("button", { name: /save/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/verification failed/i);

  fireEvent.click(screen.getByRole("button", { name: /save/i }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(2));
  expect(save.mock.calls[1][0].id).toBe(42);  // PATCH, not a second POST
});

it("warns about a big LOOPING video and not about a click-to-play one", async () => {
  renderModal({ banner: null });
  await pickVideo(fileOfSize(9_000_000));

  fireEvent.click(screen.getByRole("radio", { name: /loop/i }));
  expect(screen.getByRole("status")).toHaveTextContent(/every visitor/i);

  fireEvent.click(screen.getByRole("radio", { name: /click/i }));
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
```

Write `renderModal`, `pickVideo`, `smallMp4` and `fileOfSize` as local helpers matching the existing tests' style in that file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd admin; npm test -- --run src/components/content/__tests__/HomeBannerModal.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `HomeBannerModal.tsx`:

1. Add `videoMode` state initialised from `banner?.video_mode ?? "loop"`, and include `video_mode: videoMode` in the `saveBannerAction` payload.
2. Render a two-option radio group (`Loop silently` / `Play on click`), shown only when a video is staged or already attached.
3. Below it, when `videoMode === "loop"` and the staged video exceeds `LOOP_WARN_BYTES`, render a `role="status"` warning: *"At {size}, this loop downloads for every visitor — many on mobile data. Under 6 MB is a better target, or switch to Play on click."*
4. In `stageFile`, keep the existing cap check for images; for video use `VIDEO_CAP_BYTES` and **do not** call `downscaleImage`.
5. In the save loop, replace the video slot's single `uploadBannerMediaAction` call with ticket → `uploadToS3` → `finalizeVideoAction`, then `attachBannerMediaAction(id, "video", asset.id)`. Leave the image slots untouched.
6. Preserve `savedIdRef` and the per-slot unstaging exactly as they are — that is what makes the retry a PATCH.

In `admin/src/lib/banners.ts`, update the hero guide string:

```ts
    guide: "Image 1920×1080, or mp4/webm up to 128 MB (the image becomes the poster). A looping video should be under 6 MB — it downloads for every visitor. 2+ slides make the slider rotate.",
```

- [ ] **Step 4: Run tests**

Run: `cd admin; npm test -- --run && npm run typecheck && npm run lint && npm run build`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add admin/src/components/content/HomeBannerModal.tsx admin/src/lib/banners.ts admin/src/components/content/__tests__/HomeBannerModal.test.tsx
git commit -m "feat(admin): tile editor uploads big video and chooses how it plays"
```

---

### Task 10: Storefront playback

**Files:**
- Create: `storefront/src/components/home/ClickToPlayVideo.tsx`
- Modify: `storefront/src/lib/cms.ts`
- Modify: `storefront/src/components/home/TileMedia.tsx:19-31`
- Modify: `storefront/src/components/home/HeroSlider.tsx:113-122`
- Test: `storefront/src/components/home/__tests__/TileMedia.test.tsx`

**Interfaces:**
- Consumes: `video_mode` from Task 1's public serializer
- Produces: nothing later tasks depend on

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { TileMedia } from "@/components/home/TileMedia";

const base = { placement: "hero", sort: 0, title: "", subtitle: "", tagline: "",
               cta_text: "", cta_url: "", image: "", mobile_image: "" };

it("loop mode autoplays but no longer preloads the whole file", () => {
  const { container } = render(
    <TileMedia tone="x" banner={{ ...base, video_url: "https://cdn/x.mp4", video_mode: "loop" }} />,
  );
  const video = container.querySelector("video")!;
  expect(video).toHaveAttribute("autoplay");
  expect(video).toHaveAttribute("loop");
  expect(video).toHaveAttribute("preload", "metadata");
});

it("click mode renders NO video element until the visitor asks for one", () => {
  const { container } = render(
    <TileMedia tone="x" banner={{ ...base, video_url: "https://cdn/x.mp4",
                                  video_mode: "click", image: "https://cdn/p.jpg" }} />,
  );
  expect(container.querySelector("video")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: /play/i }));
  expect(container.querySelector("video")).not.toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd storefront; npm test -- --run src/components/home/__tests__/TileMedia.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Add `video_mode` to the type**

In `storefront/src/lib/cms.ts`, add to `CmsBanner`:

```ts
  /** "loop" autoplays silently; "click" waits for the visitor. Defaults to loop
   * server-side, so a banner from before this field behaves exactly as it always did. */
  video_mode: "loop" | "click";
```

- [ ] **Step 4: Create the client component**

`TileMedia` is a Server Component, so the interaction has to live in its own client module.

Create `storefront/src/components/home/ClickToPlayVideo.tsx`:

```tsx
"use client";

/** A poster with a play button; the <video> is only mounted once pressed.
 *
 * That is the entire point: a 3-minute film is tens of megabytes, and most visitors on
 * mobile data will never press play. Rendering the element up front — even paused —
 * invites the browser to start fetching.
 */
import Image from "next/image";
import { useState } from "react";

export function ClickToPlayVideo({ src, poster, label }: {
  src: string;
  poster: string | null;
  label: string;
}) {
  const [playing, setPlaying] = useState(false);

  if (playing) {
    return (
      <video
        className="absolute inset-0 h-full w-full object-cover"
        src={src}
        poster={poster ?? undefined}
        controls
        autoPlay
        playsInline
      />
    );
  }

  return (
    <>
      {poster ? (
        <Image src={poster} alt="" fill sizes="100vw" className="object-cover" />
      ) : (
        <div aria-hidden className="absolute inset-0 bg-black/40" />
      )}
      <button
        type="button"
        onClick={() => setPlaying(true)}
        aria-label={label}
        className="absolute inset-0 grid place-items-center"
      >
        <span
          aria-hidden
          className="grid h-16 w-16 place-items-center rounded-full bg-white/90 text-2xl text-black shadow-lg transition hover:scale-105"
        >
          ▶
        </span>
      </button>
    </>
  );
}
```

- [ ] **Step 5: Branch in both render sites**

`TileMedia.tsx` — replace the `if (banner?.video_url)` block:

```tsx
  if (banner?.video_url) {
    if (banner.video_mode === "click") {
      return <ClickToPlayVideo src={banner.video_url} poster={img}
                               label={`Play the video${banner.title ? `: ${banner.title}` : ""}`} />;
    }
    return (
      <video
        className="absolute inset-0 h-full w-full object-cover"
        src={banner.video_url}
        poster={img ?? undefined}
        autoPlay
        muted
        loop
        playsInline
        // Without this the browser eagerly downloads the whole file on every visit —
        // it was missing until 2026-08-09.
        preload="metadata"
      />
    );
  }
```

Update the component's docstring, which currently says video is always "autoplay, muted, looped".

`HeroSlider.tsx` — in the `slide.video && !reduced` branch, add `preload="metadata"` to the existing element and add a `click` branch ahead of it. Keep the `!reduced` guard for loop only: click-to-play never autoplays, so reduced motion has nothing to protect against.

- [ ] **Step 6: Run tests**

Run: `cd storefront; npm test -- --run && npm run typecheck && npm run lint && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add storefront/src/components/home/ClickToPlayVideo.tsx storefront/src/components/home/TileMedia.tsx storefront/src/components/home/HeroSlider.tsx storefront/src/lib/cms.ts storefront/src/components/home/__tests__/
git commit -m "feat(storefront): honour video_mode, and stop preloading hero video eagerly"
```

---

### Task 11: Infrastructure

**⚠️ Requires Hammed's explicit go-ahead before each write.** This bucket holds the only off-box copies of the production database. Show him each command and its read-back output.

**Files:**
- Create: `infra/aws/incoming-lifecycle.json`
- Create: `infra/aws/bucket-cors.json`
- Modify: `docs/runbooks/` — add a short runbook entry

- [ ] **Step 1: Fix the CORS rule**

The live rule contains `https:tokecosmetics.com` — a malformed origin missing `//`, which has never matched a browser.

Create `infra/aws/bucket-cors.json`:

```json
{
  "CORSRules": [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST"],
      "AllowedOrigins": [
        "https://tokecosmetics.com",
        "https://admin.tokecosmetics.com",
        "http://localhost:3001"
      ],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3000
    }
  ]
}
```

Apply and read back:

```bash
aws s3api put-bucket-cors --profile toke --bucket tokecosmetics-assets-899805259502-eu-west-1-an --cors-configuration file://infra/aws/bucket-cors.json
aws s3api get-bucket-cors --profile toke --bucket tokecosmetics-assets-899805259502-eu-west-1-an
```

Expected: the returned origins all begin `https://` or `http://localhost`.

- [ ] **Step 2: Add the `incoming/` lifecycle rule**

**Read this before running it.** There is currently **no** lifecycle configuration on this bucket, and `put-bucket-lifecycle-configuration` **replaces the whole configuration rather than merging**. An empty or missing `Filter` applies to the entire bucket — which would expire every product image under `catalog/` and every database dump under `backups/`. The `Prefix` below is not optional.

Create `infra/aws/incoming-lifecycle.json`:

```json
{
  "Rules": [
    {
      "ID": "expire-unfinalized-uploads",
      "Status": "Enabled",
      "Filter": { "Prefix": "incoming/" },
      "Expiration": { "Days": 1 },
      "NoncurrentVersionExpiration": { "NoncurrentDays": 1 },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
    }
  ]
}
```

```bash
aws s3api put-bucket-lifecycle-configuration --profile toke --bucket tokecosmetics-assets-899805259502-eu-west-1-an --lifecycle-configuration file://infra/aws/incoming-lifecycle.json
aws s3api get-bucket-lifecycle-configuration --profile toke --bucket tokecosmetics-assets-899805259502-eu-west-1-an
```

Expected: exactly one rule, `Filter.Prefix` exactly `incoming/`. **If the read-back shows any rule without a prefix, or any prefix other than `incoming/`, remove the configuration immediately** with `aws s3api delete-bucket-lifecycle` and stop.

No rule is added for `backups/` — see the spec's "Out of scope" section for why (5.37 MB total, unique keys so no version accrual, and a lifecycle rule would not touch the actual risk).

- [ ] **Step 3: Add `nosniff` at CloudFront**

Distribution `E3RM3YPEKZS13G` currently has `ResponseHeadersPolicyId: null`, so no security headers reach the browser.

```bash
aws cloudfront create-response-headers-policy --profile toke --response-headers-policy-config '{
  "Name": "toke-media-security-headers",
  "SecurityHeadersConfig": {
    "ContentTypeOptions": { "Override": true },
    "StrictTransportSecurity": { "Override": true, "AccessControlMaxAgeSec": 31536000, "IncludeSubdomains": true }
  }
}'
```

Attach the returned policy id to the distribution's `DefaultCacheBehavior` via `get-distribution-config` → edit → `update-distribution` (the update requires the current `ETag` as `--if-match`). Then verify against a live object:

```bash
curl -sI https://dk4ivng9pnc2t.cloudfront.net/catalog/library/toke-dryskin.png
```

Expected: `x-content-type-options: nosniff` present. Allow a few minutes for the distribution to redeploy.

- [ ] **Step 4: Commit the infra files**

```bash
git add infra/aws/ docs/runbooks/
git commit -m "chore(infra): bucket CORS fix, incoming/ lifecycle rule, CDN nosniff"
```

---

### Task 12: Live verification

Typecheck and green tests are not proof the feature works. Nothing here is done until these pass against production.

- [ ] **Step 1: Deploy backend and admin**

Follow the existing deploy runbook. Confirm the migration applied: `uv run python manage.py showmigrations cms` lists `0008_banner_video_mode` as applied.

- [ ] **Step 2: Upload a real video**

In the live admin, attach a genuine ~50 MB mp4 to a hero tile. Watch the progress bar advance and the save complete.

- [ ] **Step 3: Verify the object moved correctly**

```bash
aws s3 ls --profile toke s3://tokecosmetics-assets-899805259502-eu-west-1-an/incoming/
aws s3api head-object --profile toke --bucket tokecosmetics-assets-899805259502-eu-west-1-an --key catalog/library/<the-new-key>
```

Expected: `incoming/` empty; the library object exists with `ContentType: video/mp4` and an `immutable` `CacheControl`.

- [ ] **Step 4: Verify both playback modes on the storefront**

Set the banner to **loop**: it autoplays silently. Switch to **click**: the poster shows with a play button, and the Network tab records **no request for the mp4** until it is pressed.

- [ ] **Step 5: Verify the rejection path**

Rename a JPEG to `.mp4` and attempt to upload it. Expected: it uploads, then finalize refuses with "That file isn't an mp4 or webm video", and `incoming/` is left empty.

- [ ] **Step 6: Confirm the headers**

```bash
curl -sI https://dk4ivng9pnc2t.cloudfront.net/catalog/library/<the-new-key>
```

Expected: `x-content-type-options: nosniff` and `content-type: video/mp4`.

- [ ] **Step 7: Report to Hammed**

Show him the lifecycle read-back, the head-object output, and the two playback modes working. Get sign-off before closing.

---

## Self-Review

**Spec coverage:** presigned POST + exact key (T4), quarantine prefix (T3), chokepoint guard (T3), `CopySourceIfMatch` (T5), `MetadataDirective=REPLACE` (T5), idempotent finalize (T6), `head_object` re-check (T6), audit parity (T6), CORS + CSP + nosniff (T7, T11), 128 MB single constant (T3), loop warning on mode (T9), `video_mode` (T1, T9, T10), `preload` fix (T10), moto (T4), adversarial guard tests (T3), sniff table (T2), duplicate-banner regression (T9), live verification (T12). No spec section is unimplemented.

**Naming consistency checked:** `assert_incoming` / `new_incoming_key` / `library_key_for` / `mint_video_post` / `head_incoming` / `read_incoming_head` / `publish_incoming` / `discard_incoming` are used identically in Tasks 3–6. `UploadTicket` has one definition (`admin/src/lib/upload-types.ts`) imported by both the browser helper and the server actions. `VIDEO_CAP_BYTES` / `LOOP_WARN_BYTES` come only from `@/lib/video`. `MAX_VIDEO_BYTES` has exactly one definition.

**Known soft spots for the implementer:** Tasks 8 and 9 describe wiring against components whose exact props were not fully read while planning — read each component first and follow its existing conventions rather than the shapes sketched here. The migration number `0008` was confirmed against `backend/apps/cms/migrations/` while planning (latest is `0007_mediaasset_banner_image_asset_and_more.py`), but re-check before writing in case another branch has landed one since.
