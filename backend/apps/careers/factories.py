"""Test helpers for the careers board. Kept out of `tests/` so an admin shell and a
future management command can use them too, matching `apps.stores.factories`."""
from django.utils import timezone

from apps.careers.models import JobLocation, JobPosting
from apps.core.models import Country


def posting(title="Sales Representative", *, status="open", locations=(), **overrides):
    """One posting, open by default, with whatever locations were asked for.

    OPEN by default because the interesting tests are about a live board; a draft is a
    deliberate `status="draft"`, which reads at the call site as the exception it is.
    """
    country = overrides.pop("country", None) or Country.objects.get(code="NG")
    job = JobPosting.objects.create(
        title=title,
        status=status,
        country=country,
        description=overrides.pop("description", "<p>What you will be doing.</p>"),
        published_at=timezone.now() if status == "open" else None,
        **overrides,
    )
    for index, label in enumerate(locations):
        JobLocation.objects.create(job=job, label=label, sort_order=index)
    return job


# The smallest byte strings each sniffer accepts. Real files, structurally: a PDF header,
# an OLE2 signature, and a ZIP local-file header naming `[Content_Types].xml` the way
# Word writes one.
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"
DOC_BYTES = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
DOCX_BYTES = (
    b"PK\x03\x04"
    + b"\x14\x00\x06\x00\x08\x00\x00\x00!\x00"   # version/flags/method/mod time/date
    # crc32 + compressed size + uncompressed size: 12 bytes, so that the file-name
    # length lands at offset 26 where the sniffer reads it. Getting this wrong is how
    # the first draft of this fixture made a valid docx look invalid.
    + b"\x00" * 12
    + len(b"[Content_Types].xml").to_bytes(2, "little")  # file name length (offset 26)
    + b"\x00\x00"                                  # extra field length
    + b"[Content_Types].xml"
    + b"\x00" * 32
)
# A Windows executable wearing a .pdf name — the case an extension allow-list misses and
# the magic-byte sniff is for.
EXE_BYTES = b"MZ\x90\x00\x03" + b"\x00" * 64
