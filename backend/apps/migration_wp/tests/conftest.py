import json
import shutil
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "catalog-export-sample.json"


@pytest.fixture
def artifact_path(tmp_path):
    """A copy of the sample artifact, so a test can mutate it freely."""
    dest = tmp_path / "catalog-export.json"
    shutil.copy(FIXTURE, dest)
    return dest


@pytest.fixture
def artifact():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def uploads_root(tmp_path):
    """Fake wp-content/uploads. Every attachment exists EXCEPT the -MISSING one,
    so the broken-image path gets exercised."""
    root = tmp_path / "uploads"
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for rel in data["attachments"].values():
        if "MISSING" in rel:
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
    return root
