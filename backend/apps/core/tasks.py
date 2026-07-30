from celery import shared_task


@shared_task
def ping():
    """Trivial demo task used to prove the Celery wiring works."""
    return "pong"


@shared_task
def tombstone_search_terms() -> int:
    """Daily: blank the TERM in global-search audit rows older than 90 days (Plan-16 Task 6).

    A thin wrapper on purpose. The logic lives in `apps.core.audit`, which is the only
    module the audit guard exempts from the "nothing updates an audit row" AST sweep, and
    `test_audit_guard.py` pins this function as its single call site. Putting the update
    here instead would either fail that sweep or require widening it, and the whole value
    of that sweep is that widening it is expensive.

    Daily rather than hourly because the window is measured in days: a term surviving an
    extra few hours past its ninetieth day is not the risk the window exists to bound.

    Returns the number of rows tombstoned, which Celery records — a sweep that silently
    stops finding rows (a renamed model label, a beat entry dropped) then shows up as a
    permanent zero rather than as nothing at all.
    """
    from apps.core.audit import tombstone_expired_search_terms

    return tombstone_expired_search_terms()
