"""Put `queue_tags` in front of a connection that is REALLY in autocommit.

── WHY THIS EXISTS AT ALL ──────────────────────────────────────────────────────────────

`apps/catalog/revalidate.py` has two delivery paths and they diverge on one question:
`connection.in_atomic_block`. Under `pytest.mark.django_db` that question has exactly one
answer — True — because the harness wraps every test in a transaction it rolls back. So
the autocommit half of the module was, for its whole life, unreachable by the test suite.
It shipped broken (the `on_commit` hook was registered before the tag set was filled, so
`_flush` ran inline against an empty set and delivered nothing) and 3,730 green tests had
nothing to say about it.

── WHY NOT `django_db(transaction=True)` ───────────────────────────────────────────────

That is the obvious answer and it is the wrong one HERE. A transactional test flushes
every table at teardown, including the Country and Currency rows that come from data
migrations, and nothing restores them for the tests that run afterwards — `serialized_rollback`
restores at the setup of the test that asks for it, not at the teardown that emptied the
database. Measured on this suite: running `apps/orders/tests/test_state.py` (which has one
such test) immediately before `apps/catalog/tests/test_purchasable_variant_count.py` turns
the latter into 9 errors and 9 failures, and `serialized_rollback = True` does not change
it. The suite passes today only because the file order happens to be kind. Adding more
transactional tests to buy coverage here would be paying for it with everyone else's.

── WHAT THIS DOES INSTEAD ──────────────────────────────────────────────────────────────

Opens a SECOND, real connection to the same test database with
`connections.create_connection`. It is a genuine `DatabaseWrapper`: not inside the
harness's atomic block, genuinely in autocommit, and its `on_commit` is Django's own — the
one that runs the callback inline instead of deferring it. That is the exact condition a
management command, a Celery task, a shell, or any dev/staging request reaches, reproduced
without emptying a single table.

The shim below is not a stand-in for the transaction layer; it is `django.db.transaction`'s
two functions, re-bound to that connection. `on_commit` still ends in
`BaseDatabaseWrapper.on_commit`, so the run-now-or-defer decision is still Django's and
still made against real connection state. A mock that answered that question itself would
be worthless — it is the only question in the module.
"""

from __future__ import annotations

import contextlib

from django.db import connections

from apps.catalog import revalidate as catalog_revalidate


@contextlib.contextmanager
def real_autocommit_connection(monkeypatch, *, autocommit: bool = True):
    """Point `apps.catalog.revalidate` at a real, unwrapped connection.

    `autocommit=False` leaves it in MANUAL transaction management instead — the third
    state, where the write is not committed and Django offers no commit hook at all.
    """
    conn = connections.create_connection("default")
    try:
        conn.ensure_connection()
        if not autocommit:
            conn.set_autocommit(False)

        # The premise, asserted rather than assumed: if a future Django ever wrapped a
        # freshly created connection, these tests would otherwise go quietly vacuous and
        # start passing for the wrong reason.
        assert conn.in_atomic_block is False
        assert conn.get_autocommit() is autocommit

        class _TransactionBoundTo:
            """`django.db.transaction`'s API, bound to `conn` instead of the default."""

            @staticmethod
            def get_connection(using=None):
                return conn

            @staticmethod
            def on_commit(func, using=None, robust=False):
                # Django's own `transaction.on_commit` body, verbatim.
                return conn.on_commit(func, robust)

        monkeypatch.setattr(catalog_revalidate, "transaction", _TransactionBoundTo)
        yield conn
    finally:
        # Manual mode leaves an open transaction on a real connection; roll it back before
        # closing so the test database is not left holding locks for whatever runs next.
        if conn.connection is not None and not conn.get_autocommit():
            conn.rollback()
            conn.set_autocommit(True)
        conn.close()
