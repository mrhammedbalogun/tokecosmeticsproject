"""Turning a `ProtectedError` from a combo into a sentence somebody can act on.

`ComboItem.variant` is `PROTECT` deliberately (see `apps/combos/models.py`): a variant
disappearing out of a live bundle would leave it selling a smaller box at the same price,
so the delete must fail. What it must NOT do is fail as a 500 — the person deleting has a
real job to finish, and "Cannot delete some instances of model 'ProductVariant' because
they are referenced through protected foreign keys" names neither the combo nor the way
out.

Lives in `catalog` rather than `combos` because catalog is where the deletes happen, and
a helper is cheaper than teaching two viewsets the same paragraph. It reads `exc`'s own
protected objects rather than re-querying, so it can only ever name the rows that
actually blocked THIS delete.
"""
from __future__ import annotations

MAX_NAMED = 5


def combos_holding(exc, what: str) -> str:
    """A refusal naming the combos that blocked the delete.

    `ProtectedError.protected_objects` is whatever held the reference. Anything that is
    not a `ComboItem` is not ours to explain, so the message falls back to a generic
    sentence rather than claiming a combo is at fault when something else is.
    """
    from apps.combos.models import ComboItem

    names = sorted(
        {obj.combo.name for obj in exc.protected_objects if isinstance(obj, ComboItem)}
    )
    if not names:
        return (
            f"This {what} is still referenced by something else and cannot be deleted."
        )
    shown = ", ".join(names[:MAX_NAMED])
    if len(names) > MAX_NAMED:
        shown += f" and {len(names) - MAX_NAMED} more"
    plural = "combo" if len(names) == 1 else "combos"
    return (
        f"This {what} is inside the {plural} {shown}. Remove it from "
        f"{'that combo' if len(names) == 1 else 'those combos'} first, or delete "
        f"{'it' if len(names) == 1 else 'them'} — otherwise the {plural} would sell a "
        f"smaller box at the same price."
    )
