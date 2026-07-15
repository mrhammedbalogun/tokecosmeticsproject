"""Resolve the storefront's X-Country header to a Country row.

Fallback chain:
  - header missing/blank  -> default market (NG)
  - header = active market -> that country
  - header = unknown/inactive country -> Rest of World (ZZ)
"""
from __future__ import annotations


def resolve_country(code: str | None):
    from apps.core.models import Country

    code = (code or "").strip().upper()
    if not code:
        return Country.objects.filter(is_default=True, is_active=True).first()
    country = Country.objects.filter(code=code, is_active=True).first()
    if country:
        return country
    return Country.objects.filter(is_rest_of_world=True, is_active=True).first()
