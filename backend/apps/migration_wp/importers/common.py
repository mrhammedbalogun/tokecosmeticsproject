"""Shared constants and logger for the migration_wp importers package.

Every importer module in this package imports `logger` and `LEGACY_SOURCE`
from here rather than creating its own, so all import-phase log records share
one logger name.
"""
from __future__ import annotations

import logging

LEGACY_SOURCE = "wp_ng"

logger = logging.getLogger("apps.migration_wp.importers")
