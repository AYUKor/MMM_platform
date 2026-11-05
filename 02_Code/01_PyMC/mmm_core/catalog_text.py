"""Display rules shared by the catalog build, the reasons step and the catalog extension (standard library only)."""
from __future__ import annotations

import math
import re


def split_percents(kept: float, own: float, overlap: float) -> tuple[int, int, int]:
    """Whole percents of the three parts that always add up to 100 (largest remainder, ties by order).
    The portal card and the Excel round the same way, so the text and the bar show the same numbers."""
    raw = [100.0 * max(float(v), 0.0) for v in (kept, own, overlap)]
    total = sum(raw)
    if total <= 0:
        return 0, 0, 0
    raw = [v * 100.0 / total for v in raw]
    out = [math.floor(v) for v in raw]
    for i in sorted(range(3), key=lambda j: (-(raw[j] - out[j]), j))[:100 - sum(out)]:
        out[i] += 1
    return out[0], out[1], out[2]


def geo_display(name: str) -> str:
    """City or region label as shown: words inside parentheses in lower case («(кроме городов)»)."""
    return re.sub(r"\(([^)]*)\)", lambda m: "(" + m.group(1).lower() + ")", str(name))


__all__ = ["geo_display", "split_percents"]
