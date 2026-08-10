"""End-to-end for the presigned video path. See
docs/superpowers/specs/2026-08-09-presigned-video-uploads-design.md."""
import boto3
import pytest
from moto import mock_aws
from rest_framework.test import APIClient

from apps.catalog.tests.factories_admin import staff_user
from apps.cms.models import MediaAsset
from apps.cms.s3_uploads import library_key_for

BUCKET = "test-bucket"
MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00\x00\x01\x00moov" + b"\x00" * 2048
TICKET = "/api/v1/admin/media/video-ticket/"
FINALIZE = "/api/v1/admin/media/video-finalize/"


@pytest.fixture
def client():
    c = APIClient()
    c.force_authenticate(user=staff_user())
    return c


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
    assert r.status_code == 200, r.content
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
def test_finalize_rechecks_the_real_size_even_when_the_ticket_lied(client, s3):
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


@pytest.mark.django_db
def test_both_endpoints_require_marketing_manage():
    content_editor = APIClient()
    content_editor.force_authenticate(user=staff_user(email="content@toke.test", role="Content"))
    body = {"filename": "a.mp4", "size": 10, "container": "mp4"}
    assert content_editor.post(TICKET, body, format="json").status_code == 403
    assert content_editor.post(FINALIZE, {"key": "incoming/x.mp4", "original_name": "x"},
                               format="json").status_code == 403
    assert APIClient().post(TICKET, body, format="json").status_code in (401, 403)
    assert APIClient().post(FINALIZE, {"key": "incoming/x.mp4", "original_name": "x"},
                            format="json").status_code in (401, 403)
