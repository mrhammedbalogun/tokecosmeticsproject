"""Every uploaded file must land under `catalog/`, because that is all the CDN serves.

── WHAT THIS PREVENTS, AND WHY A COMMENT WAS NOT ENOUGH ────────────────────────────

The assets bucket is PRIVATE and must stay private: the nightly Postgres dumps live in
it under `backups/` (`infra/deploy/backup.sh`), so making objects publicly readable would
mean switching Block Public Access off on the bucket holding the database. CloudFront
reaches it through an Origin Access Control instead, and that policy is scoped to
`catalog/*` — deliberately narrow, so `backups/` stays unreachable even through the CDN.

The failure mode is nasty precisely because nothing errors. A model with
`upload_to="somewhere-else/"` uploads successfully, `storage.exists()` returns True,
`.url` returns a perfectly well-formed URL — and the CDN answers 403. It presents as "the
image is broken" with a green path all the way through the application.

It has now happened twice. `apps/cms` hit it and moved its banners to
`catalog/cms-banners/`; `apps/combos` hit it again on 2026-09-03 with `upload_to="combos/"`,
and the first real combo's featured image was a broken thumbnail in the admin. The
settings block explained the rule the whole time. So the rule is a test now.

DISCOVERED FROM THE MODEL REGISTRY, not a hand-written list: a model added next month is
checked without anybody remembering to add it here.
"""
import pytest
from django.apps import apps as django_apps
from django.db.models import FileField

# The one prefix CloudFront's OAC policy allows. If this ever legitimately grows, the AWS
# policy has to grow WITH it — and whoever does that should be the one editing this line.
SERVABLE_PREFIX = "catalog/"

# Fields whose bytes are never served to a browser. Each entry says why, because "it is
# in the exemption list" is not a reason.
EXEMPT: dict[str, str] = {}


def _upload_fields():
    for model in django_apps.get_models():
        for field in model._meta.get_fields():
            if isinstance(field, FileField):
                yield f"{model._meta.label}.{field.name}", field


def test_every_uploaded_file_lands_where_the_cdn_can_serve_it():
    offenders = []
    for label, field in _upload_fields():
        if label in EXEMPT:
            continue
        upload_to = field.upload_to
        # A callable `upload_to` computes the path at save time and cannot be read here.
        # None exists today; if one is added, it needs its own test rather than a pass.
        assert not callable(upload_to), (
            f"{label} uses a callable upload_to, which this guard cannot read. "
            "Give it a test that asserts the prefix it produces."
        )
        if not str(upload_to).startswith(SERVABLE_PREFIX):
            offenders.append(f"{label} -> {upload_to!r}")

    assert not offenders, (
        "these uploads land outside the only prefix CloudFront serves, so their files "
        f"will 403 at the CDN while every other signal says they saved fine: {offenders}. "
        f"Use '{SERVABLE_PREFIX}<something>/' — see apps/combos/migrations/0002."
    )


@pytest.mark.django_db
def test_the_combo_image_is_one_of_them():
    """The specific regression, named. `apps/combos` is where this bit us."""
    from apps.combos.models import Combo

    assert Combo._meta.get_field("image").upload_to == "catalog/combos/"
