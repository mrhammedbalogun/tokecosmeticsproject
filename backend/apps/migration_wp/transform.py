"""Pure transforms from WordPress shapes to platform shapes.

Every function here takes plain data and returns plain data — no Django models,
no database, no network. That keeps the migration's real logic unit-testable
without a MySQL service in CI.
"""
from __future__ import annotations

import re

# Editor paste artifacts: <p data-start="162" data-end="542">
_DATA_ATTR_RE = re.compile(r'\s+data-(?:start|end)="[^"]*"')
_NBSP_RE = re.compile(r"(&nbsp;| )")


def clean_description(html: str | None) -> str:
    """Strip editor artifacts from WooCommerce product HTML.

    The content is human-written prose in simple HTML (verified 2026-07-25:
    no Elementor, no shortcodes, no embedded images). Only two artifacts need
    removing, and real markup must survive untouched.
    """
    if not html:
        return ""
    out = _DATA_ATTR_RE.sub("", html)
    out = _NBSP_RE.sub(" ", out)
    return out.strip()
