# Presigned direct-to-S3 video uploads

**Date:** 2026-08-09
**Status:** design approved, awaiting implementation plan
**Scope:** the upload transport for video only. Images are not touched.

## The problem

Admin media uploads die above 4 MB.

Measured against the live admin domain on 2026-08-09:

| Request body | Result |
|---|---|
| 3.91 MB | HTTP 200 |
| 4.30 MB | HTTP 413 |
| 4.49 MB | HTTP 413 |
| 4.88 MB | HTTP 413 |

The 413 arrives *instead of* the login challenge, which proves Vercel's edge rejects the
request before any application code runs. It is not a setting we can raise:
`admin/next.config.ts` already declares `serverActions.bodySizeLimit = "85mb"`, but Next
never parses the body, so that ceiling is unreachable on Vercel. It applies only when
self-hosting.

The cause is the shape of the path, not the size of a constant:

```
browser -> Next server action (Vercel) -> Django API (VPS) -> S3 -> CloudFront
                      ^
                      the only 4.5 MB constraint in the chain
```

Django's own guard allows 80 MB of video; S3 allows 5 GB. Only the relay is small.

## What the owner needs

Gathered 2026-08-09:

- **Images:** keep client-side downscaling under 4 MB. Quality must not visibly degrade;
  the page-speed benefit is wanted. **The image path therefore already works and is out
  of scope.**
- **Homepage hero:** a 10-20s silent autoplay loop.
- **Homepage film section:** a 2-3 minute film, click-to-play behind a poster. Roughly
  45-110 MB as the owner imagines it; see "Size ceiling" for why the answer is an encode
  recipe rather than a bigger number.
- **Product galleries:** short video alongside product images. Explicitly deferred to its
  own spec.

Only video is broken, so only video changes. Scoping this to video keeps the full-byte
Pillow `.verify()` on the image path exactly as it is, and makes the new header sniff a
strict *upgrade* for video, which today is classified purely by whether the filename ends
in `.mp4` or `.webm` (`backend/apps/cms/admin_serializers.py:31-32`) - pure client input.

## Verified environment facts

All confirmed against the live AWS account and production on 2026-08-09. Several
contradict earlier assumptions, including one in this project's own memory notes.

| Fact | Value | How confirmed |
|---|---|---|
| Bucket | `tokecosmetics-assets-899805259502-eu-west-1-an`, eu-west-1 | prod `infra/.env` |
| Public Access Block | all four flags `true` | `get-public-access-block` |
| Bucket policy | `s3:GetObject` on **`catalog/*` only**, with a `SourceArn` condition | `get-bucket-policy` |
| **Versioning** | **`Enabled`** | `get-bucket-versioning` |
| Lifecycle config | **none exists** | `NoSuchLifecycleConfiguration` |
| CORS | exists, but `AllowedOrigins` contains the malformed `https:tokecosmetics.com` (missing `//`) | `get-bucket-cors` |
| CloudFront | distribution `E3RM3YPEKZS13G`, `ResponseHeadersPolicyId: null` | `get-distribution-config` |
| `nosniff` on CDN responses | **absent** | live `curl -I` against a real asset |
| gunicorn | 3 sync workers, shared with the storefront API | `backend/Dockerfile` |
| Backup credential | the **`web` container** holds the credential that writes `backups/` | `infra/deploy/backup.sh` header comment |

Two of these change decisions:

**Versioning is enabled.** The memory note `project_tokecosmetics_s3_backup_risk.md` says
it is off, and a design review proceeded on that basis. It is on. A mis-scoped expiration
rule therefore writes a delete marker rather than destroying the only copy. The precautions
below stay regardless; the worst case is recoverable, not unrecoverable.

**The bucket policy really is scoped to `catalog/*`.** This is what makes the quarantine
prefix work: an object under `incoming/` is unreachable through the CDN by construction,
not by convention.

## Approach

Chosen: **presigned POST into a quarantine prefix, verified server-side, then copied into
`catalog/`.**

### Rejected alternatives

**Presigned PUT.** Simpler, but a presigned PUT cannot carry a `content-length-range`
condition, so the size ceiling becomes a promise checked after the fact rather than a rule
S3 enforces. Presigned POST's policy conditions are the documented, boring mechanism.

**Browser posts directly to the Django API**, skipping S3 presigning, relying on
Cloudflare's 100 MB body limit. Rejected on three counts. Cloudflare's 100 MB is a hard
wall a long film could hit. Production runs **3 sync gunicorn workers shared with the
storefront API**, so a 110 MB upload from a slow uplink pins a third of the store's
capacity for minutes. And the admin's BFF model means the browser holds no API credential
at all - this would require issuing one, undoing the gate added in v0.4.1.

## Data flow

```
1. admin picks a video
2. browser --> Next server action --> Django  POST /admin/media/video-ticket/
                  (tiny JSON)           (admin JWT; BFF unchanged)
3. Django returns a one-shot S3 POST form:
     key    = incoming/<uuid4>.<ext>    <- server-generated, exact, never client input
     policy = content-length-range 1..CAP, expires 30 min
```

`<ext>` is **not** taken from the client's filename. It is clamped to a two-item
allow-list (`.mp4`, `.webm`) chosen from the sniffed kind at finalize and from the
declared kind at ticket time; anything else is refused before a ticket is minted. A
client-supplied extension would otherwise be client input inside a key we call
server-generated. The client's original filename is still recorded, but only as
`MediaAsset.original_name` (truncated to 255 chars), never as part of any S3 key.

```
4. browser ==> S3 directly, via XHR with progress   <- bytes never touch Vercel
5. browser --> Next server action --> Django  POST /admin/media/video-finalize/
6. Django finalizes (below)
```

Finalize, in order:

1. Assert the key is under `incoming/` (via the chokepoint, below).
2. `head_object` - real `ContentLength` and `ETag`. Re-check the ceiling against what
   actually landed, never against what the ticket request claimed.
3. Ranged `get_object` of the first 256 KB. Sniff container magic: `ftyp` box for MP4,
   EBML `1A45DFA3` for WebM. Also detect `moov`/`mdat` ordering so a non-faststart file
   can be flagged - it would otherwise refuse to play until fully downloaded.
4. `copy_object` to `catalog/library/<uuid>.<ext>` with `CopySourceIfMatch=<ETag from
   step 2>`, `MetadataDirective="REPLACE"`, `ContentType` from our own sniff, and a long
   `Cache-Control`.
5. `get_or_create` the `MediaAsset` on the deterministic destination key.
6. Best-effort delete of the `incoming/` object. Failure must **not** fail the request;
   the lifecycle rule is the backstop.
7. Write the audit row.

Assigning an S3 key string straight to the `FileField` is existing practice in this
codebase, not a new trick - see `admin_serializers.py:186` ("A string assigns the KEY").

### Properties this shape guarantees

1. **The browser never chooses a key.** A server-generated UUID, pinned as an exact-match
   condition rather than `starts-with`. No client-supplied string can place bytes near
   `backups/`.
2. **The browser never receives an API credential.** The ticket request travels the normal
   server-action path, so the BFF model is untouched. What the browser gets is a
   short-lived credential to write exactly one S3 key.
3. **Unverified bytes are never public.** `incoming/` sits outside the bucket policy's
   `catalog/*` scope.
4. **The copy is the commit point, welded to the sniff by `CopySourceIfMatch`.** Without
   it, a ticket holder could replace the bytes between our sniff and our copy.

## Components

| Module | Responsibility |
|---|---|
| `backend/apps/cms/s3_uploads.py` *(new)* | The **only** module that talks to S3 for this flow. Ticket minting, head, ranged sniff, guarded copy, guarded delete. Holds the single `incoming/` prefix assert. |
| `backend/apps/cms/admin_views.py` | Two new actions on `MediaAssetAdminViewSet`, both `marketing.manage`, both audited. |
| `backend/apps/cms/admin_serializers.py` | Ticket request/response serializers; video magic-byte sniff. Existing image validation untouched. |
| `admin/src/lib/upload.ts` *(new)* | XHR upload with progress and abort. XHR rather than `fetch` because `fetch` reports no upload progress. |
| `admin/src/app/(shell)/content/media/actions.ts` | Two new server actions. |
| `MediaLibraryModal.tsx`, `HomeBannerModal.tsx` | Video slots rewired to the new path. Image slots unchanged. |

## Security hardening

Each of these is mandatory, and each exists for a specific failure:

1. **One chokepoint with the `incoming/` assert.** Every delete and every copy-source goes
   through a single function. `backup.sh` confirms the Django container's credential can
   delete the Postgres dumps, so a delete path in this code is a loaded gun. One guarded,
   unit-tested function - not asserts scattered across call sites.
2. **`CopySourceIfMatch`** pinned to the sniffed ETag. Closes the TOCTOU window.
3. **`MetadataDirective="REPLACE"`** with a server-set `ContentType`. Without the flag the
   client's declared type is copied through silently, defeating the point of sniffing.
4. **Idempotent finalize** - deterministic destination key plus `get_or_create`.
5. **Ceiling re-checked from `head_object`**, never trusted from the ticket request.
6. **Lifecycle rule with an explicit `Filter.Prefix = "incoming/"`**, read back with
   `get-bucket-lifecycle-configuration` after creation and shown to the owner. Covers both
   current and noncurrent versions, since versioning is on.
7. **Audit parity.** Both endpoints audit explicitly; they bypass the serializer whose
   `audit_allowlist` provides it today.

### Prerequisite infrastructure changes

- **Fix the CORS typo** (`https:tokecosmetics.com` -> `https://tokecosmetics.com`) and add
  `https://admin.tokecosmetics.com` with `POST` allowed.
- **Add the bucket origin to `connect-src`** in `admin/src/lib/csp.ts` - it currently lists
  only `'self'`, the API origin and Turnstile, so the browser cannot reach S3.
- **Attach a CloudFront response-headers policy** carrying
  `X-Content-Type-Options: nosniff`. Currently none is attached and the header is absent.
  Worth doing irrespective of this project.

## Size ceiling

`MAX_VIDEO_BYTES` is 80 MB; the film is imagined at 45-110 MB. Resolution: set the S3
policy ceiling to **128 MB** as a guardrail, and solve the real problem at the encode -
720p H.264 at roughly 2-2.5 Mbps with `+faststart` lands a 3-minute film at 45-55 MB.

**There must be exactly one video ceiling constant, and both paths must read it.**
`MAX_VIDEO_BYTES` is raised to 128 MB and imported by `s3_uploads.py` for the
`content-length-range` condition and by the `head_object` re-check. It is not duplicated.
The failure mode being designed out is a future reader assuming the serializer's constant
governs a path that never touches the serializer - which is exactly the confusion that
let `next.config.ts`'s unreachable 85 MB sit there looking authoritative.

### What happens to the old video upload path

The existing multipart upload through `MediaAssetAdminSerializer` is **kept, not removed.**
It remains the only path for images (with its full-byte Pillow check intact) and stays
available to direct API clients for video. What changes is narrow: the admin UI routes
**all** video through the presigned path, regardless of size, so there is one video code
path in the UI rather than a size-dependent fork. Removing it would break API clients for
no benefit; leaving it does not
weaken anything, because it enforces the same ceiling from the same constant and its
`sniff_kind` is strictly weaker only on the extension question, which the admin UI no
longer relies on.

The hero loop needs a *different* limit and for a different reason. The film is
click-to-play, so its bytes are opt-in; the hero loop downloads automatically for every
homepage visitor, many on Nigerian mobile data. A 25 MB loop is not a loop. Target 3-5 MB
(10-15s, 720p, muted, no audio track). The editor warns above ~6 MB on a hero placement -
a warning, not a block.

## Failure handling

Governing principle, inherited from the bug that started this: **every failure produces a
sentence, and the modal never spins forever.**

`file.size` is known at pick time, so anything over the ceiling is refused before a byte
is uploaded, with its measured size and the encode recipe.

| Failure | Message | Bytes |
|---|---|---|
| Ticket request | "Could not start the upload - check the connection and try again." | nothing staged |
| Upload drops mid-transfer | "The upload stopped at N%. Large videos can't resume - press Retry to start it again." | orphan in `incoming/`; lifecycle reclaims |
| S3 policy rejection | translated from S3's XML; expiry -> "That took longer than 30 minutes. Choose the file again." | nothing stored |
| Sniff says not a video | "That file isn't an mp4 or webm video." (the existing sentence) | deleted via chokepoint |
| `CopySourceIfMatch` mismatch | "The upload could not be verified. Please try again." + Sentry | deleted |
| Finalize never called | none - the admin has left | orphan; lifecycle reclaims. Retrying the same ticket still works. |

### Accepted limitations

**No resume.** A presigned POST is one request; a failed 90 MB upload restarts from zero.
Multipart upload would fix it and is deliberately excluded - it roughly doubles the
complexity of a path maintained by one person, for a surface used a few times a month. The
UI says so rather than pretending otherwise.

**The hero warning does not block.** It states the cost to mobile customers and lets the
owner proceed.

### Interaction with the 2026-08-09 banner-modal fix

`HomeBannerModal` now saves text first, then chases the row id with each media slot,
unstaging each slot as it succeeds (commit `8935354`). Video becomes a three-step slot
(ticket -> S3 -> finalize) while image slots stay single-step. The existing per-slot
unstaging handles this correctly - a video slot simply isn't cleared until finalize
returns - but it is precisely where the duplicate-banner bug could return. The plan must
call it out and a test must pin it.

## Testing

The project has no S3 test coverage today: `pyproject.toml` lists only `pytest` and
`pytest-django`, and tests run against local `FileSystemStorage` because
`AWS_STORAGE_BUCKET_NAME` is empty outside production. **Add `moto` as a dev dependency.**

Split by the kind of claim being made:

**Behaviour, under moto:**
- ticket -> upload -> finalize yields one `MediaAsset` under `catalog/library/`, nothing
  left in `incoming/`
- finalize called twice yields one row
- a ticket request that lies about size is caught by the `head_object` re-check
- sniff rejection deletes the incoming object and returns the existing sentence
- a user without `marketing.manage` gets 403 from both endpoints

**Call shape, asserted on boto3 kwargs** (moto's fidelity on conditional copy is not
something the TOCTOU defence should rest on):
- `CopySourceIfMatch` carries the ETag from the sniff
- `MetadataDirective="REPLACE"` present, `ContentType` from our sniff
- the POST policy contains `content-length-range` and an **exact** key condition

**The chokepoint, adversarially** - named tests refusing `backups/nightly.sql.gz`,
`catalog/library/x.mp4`, `incoming/../backups/x`, `""`, and `None`.

**Video sniffing, as a table** - real MP4 `ftyp`; WebM EBML; a PNG; a text file; an MP4
renamed `.png` (**accepted** - magic wins); a PNG renamed `.mp4` (**rejected** - the case
today's extension check gets wrong).

**Frontend (vitest):** pick-time refusal above the ceiling; progress callback; abort path;
each error sentence; and a regression test pinning the duplicate-banner fix through the
video slot's three-step flow.

**Live verification before this is called done:**

1. Upload a real ~50 MB video end-to-end through the admin
2. Confirm it plays from CloudFront and the `incoming/` object is gone
3. Read back the lifecycle rule and show the output
4. Confirm `X-Content-Type-Options: nosniff` now present on a CDN response
5. Confirm the CORS fix by watching a real browser upload succeed from
   `admin.tokecosmetics.com`

## Out of scope, recorded

- **Product gallery video** - needs a product model field, admin gallery work and PDP
  rendering. Its own spec.
- **The homepage film section** - a new placement, poster handling and a storefront
  section. Its own spec. This upload path unblocks it.
- **Backups sharing the media bucket.** Versioning is on, so the acute danger is lower
  than feared, but there is no lifecycle rule anywhere and noncurrent versions accumulate
  indefinitely for any overwritten key. This is the parked
  `project_tokecosmetics_s3_backup_risk.md` in new clothing, and this design has now
  collided with it twice. Recommend splitting backups into their own bucket with a
  least-privilege credential, as a separate piece of work.
