"""Flush the storefront's programme cache when the intake opens or closes.

Thin on purpose: the actual caller — a fire-and-forget daemon thread with a 3s timeout,
logged and swallowed on failure, a no-op until `REVALIDATE_SECRET` is set — lives in
`apps.cms.revalidate.notify_storefront` and is reused rather than copied. The only thing
this module owns is the NAME of the tag, which `storefront/src/lib/entrepreneurship.ts`
must match.

WHY THIS IS NOT OPTIONAL. `/entrepreneurial-program` reads `/entrepreneurship/config/`
as a tagged, revalidating fetch — it has to, because that page is inside
`(static-shop)`, whose layout forbids any per-visitor read. Without a flush, an operator
who closes the intake leaves the form on the public page for the length of the cache
window, still collecting students nobody can take. The whole point of the switch is that
it acts at the moment it is clicked.
"""

from apps.cms.revalidate import notify_storefront

STOREFRONT_TAG = "entrepreneurship"


def notify_programme_changed(*_args, created: bool = False, **_kwargs) -> None:
    """Signal receiver: a CHANGE to the singleton invalidates the one programme tag.

    CREATION IS SKIPPED, and not as an optimisation — this is the trap `apps.core
    .revalidate.notify_decisions_changed` already documents, and it bites the same way
    here. `ProgramSettings.load()` materialises the row from its field defaults on first
    touch, and those defaults (`is_open=True`) are exactly what the storefront already
    believes: its own fallback treats an unreachable config as open. Writing them down
    changes nothing anybody is looking at, so there is nothing to flush.

    It also matters practically. `load()` runs on the first config read of a fresh
    database — including inside tests, where the database rolls back between them — so
    firing on create would mean a real HTTP POST to the storefront from test setup
    wherever `REVALIDATE_SECRET` happens to be set, which on a developer machine it is.
    Skipping the create leaves exactly the firings that mean something: somebody saving
    the switch.
    """
    if created:
        return
    notify_storefront([STOREFRONT_TAG])
