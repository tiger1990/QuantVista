"""Pure alert-condition evaluation (QV-048).

``matches`` decides whether a metric value satisfies a rule's ``op``/``threshold``. A ``None`` value
(the target stock is missing that metric) never fires — no data, no alert. Ops are the QV-047
allow-list; an unknown op is treated as no-match (defensive; validation already rejects them).
"""

from __future__ import annotations

import operator
from collections.abc import Callable

_OPS: dict[str, Callable[[float, float], bool]] = {
    "gte": operator.ge,
    "lte": operator.le,
    "gt": operator.gt,
    "lt": operator.lt,
    "eq": operator.eq,
}


def matches(value: float | None, op: str, threshold: float) -> bool:
    """True iff ``value <op> threshold``; ``None`` value or unknown op → False."""
    if value is None:
        return False
    compare = _OPS.get(op)
    return compare is not None and compare(value, threshold)
