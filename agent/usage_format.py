"""Pure formatting for provider usage counters."""
import time
from typing import Optional
BAR_WIDTH = 10
BAR_FILL = "|"
BAR_EMPTY = " "
_BP_FULL = 10_000

def clamp_fraction(value: float) -> float:
    return 0.0 if value < 0.0 else min(value, 1.0)


def _filled_cells(fraction: float, width: int) -> int:
    value = clamp_fraction(fraction)
    filled = round(value * width)
    if value > 0.0 and filled == 0:
        filled = 1
    if value < 1.0 and filled == width:
        filled = width - 1
    return filled


def render_bar(fraction: float, width: int = BAR_WIDTH) -> str:
    """``[||||      ]`` — filled cells are *fraction* (usage gauges pass the USED fraction; cost bars
    their intensity). Any non-zero value shows at least one cell and a non-full one always leaves one
    empty, so "barely used" never reads as untouched and "almost out" never reads as exhausted."""
    filled = _filled_cells(fraction, width)
    return f"[{BAR_FILL * filled}{BAR_EMPTY * (width - filled)}]"


def format_percent_used(used_fraction: float) -> str:
    """Whole-percent used, same rule as the portal (``formatUsedPercentLabel``): floor, any sliver
    reads ``<1%`` (never ``0%``), and ``100%`` only once the allowance is actually exhausted."""
    # round() first: used = 1 - left can land a hair under an exact basis point (0.00999…).
    bp = int(round(clamp_fraction(used_fraction) * _BP_FULL, 6))
    if bp <= 0:
        return "0%"
    if bp < 100:
        return "<1%"
    return f"{bp // 100}%"


def compact_duration(resets_at_ms: Optional[int], now_ms: Optional[int] = None) -> str:
    """``"5h"`` / ``"2d 3h"`` / ``"12m"`` until *resets_at_ms*; ``""`` when past, under a minute or unknown."""
    if not isinstance(resets_at_ms, int):
        return ""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    seconds = max(0, (resets_at_ms - now) // 1000)
    if seconds < 60:
        return ""
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    return f"{hours}h" if hours else f"{minutes}m"


def format_resets_in(resets_at_ms: Optional[int], now_ms: Optional[int] = None) -> str:
    """``"resets in 5h"`` / ``"resets in 2d 3h"`` / ``"resets soon"`` (past or unknown → soon). English:
    ``/usage`` (untranslated, like main's credits lines); pickers use the catalog's words."""
    d = compact_duration(resets_at_ms, now_ms)
    return f"resets in {d}" if d else "resets soon"
