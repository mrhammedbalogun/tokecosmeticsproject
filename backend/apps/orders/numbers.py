"""TC-<seq> order numbers from a dedicated Postgres sequence starting at 100001.
A DB sequence (not max()+1) is gap-tolerant and concurrency-safe — two checkouts
never collide, and a rolled-back order simply burns a number (acceptable)."""
from django.db import connection

SEQUENCE_NAME = "order_number_seq"


def next_order_number() -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT nextval(%s)", [SEQUENCE_NAME])
        seq = cur.fetchone()[0]
    return f"TC-{seq}"
