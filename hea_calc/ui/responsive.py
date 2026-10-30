"""Qt-free responsive sizing rules (unit-tested without a display).

``distribute`` is the single width-allocation rule used by the upper three-panel row, the
element-property groups and the results-table columns: reference widths are the design's
(Figma frame at 1920 logical px); narrower space compresses every item proportionally to its
reference width, never below its minimum; wider space is given to the items allowed to grow.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def distribute(avail: int, refs: Sequence[int], mins: Sequence[int],
               maxs: Sequence[int | None] | None = None) -> list[int]:
    """Integer widths summing to ``avail`` (or to ``sum(mins)`` when that is larger).

    * ``avail >= sum(refs)``: every item gets its reference width, and the surplus is shared by
      the items whose ``max`` is ``None`` (or above the reference), proportionally to their
      reference widths and up to their maximum.
    * ``sum(mins) <= avail < sum(refs)``: proportional compression ``ref × s``; items that would
      fall below their minimum are pinned at it and ``s`` is recomputed for the rest.
    * ``avail < sum(mins)``: the minimums (the caller overflows / scrolls).

    Rounding remainders go to the last free item, so the result always sums exactly.
    """
    n = len(refs)
    if n == 0:
        return []
    maxs = list(maxs) if maxs is not None else [None] * n
    refs = [max(0, int(r)) for r in refs]
    mins = [min(int(m), r) if r else int(m) for m, r in zip(mins, refs)]
    if avail <= sum(mins):
        return list(mins)
    if avail >= sum(refs):
        out = list(refs)
        surplus = avail - sum(refs)
        growable = [i for i in range(n) if maxs[i] is None or maxs[i] > refs[i]]
        while surplus > 0 and growable:
            weight = sum(refs[i] for i in growable) or len(growable)
            given = 0
            capped = []
            for i in growable:
                share = math.floor(surplus * (refs[i] or 1) / weight)
                if maxs[i] is not None and out[i] + share >= maxs[i]:
                    share = maxs[i] - out[i]
                    capped.append(i)
                out[i] += share
                given += share
            surplus -= given
            growable = [i for i in growable if i not in capped]
            if not capped:
                if surplus > 0 and growable:   # rounding remainder
                    out[growable[-1]] += surplus
                    surplus = 0
                break
        return out
    # proportional compression with minimum clamps
    pinned: set[int] = set()
    while True:
        free = [i for i in range(n) if i not in pinned]
        room = avail - sum(mins[i] for i in pinned)
        weight = sum(refs[i] for i in free)
        s = room / weight if weight else 0.0
        newly = [i for i in free if refs[i] * s < mins[i]]
        if not newly:
            break
        pinned.update(newly)
    out = [mins[i] if i in pinned else math.floor(refs[i] * s) for i in range(n)]
    free = [i for i in range(n) if i not in pinned]
    rest = avail - sum(out)
    if free:
        out[free[-1]] += rest
    return out


def priority_widths(avail: int, naturals: Sequence[int], mins: Sequence[int], caps: Sequence[int],
                    primary: int, primary_share: float = 0.4) -> list[int]:
    """Column widths with one *primary* column (the results table's Alloy), content first.

    * ``naturals``: what each column needs to show its header and its visible values; ``mins``: never narrower;
      ``caps``: how wide a non-primary column may grow (its design width) - extra space is no use to a number.
    * The primary column needs ``naturals[primary]``, bounded to ``primary_share`` of the table (at least its
      minimum) so one very long name cannot crush every other column.
    * Room for everything: every column at its natural width; the surplus grows the other columns towards their
      caps (proportionally), and what is left goes to the primary column.
    * Too little room: the other columns shrink towards their minimums first (proportionally to their natural
      widths); only then the primary column, down to its minimum; below that the widths are the minimums and the
      caller scrolls.

    Widths sum to ``avail`` whenever ``avail >= sum(mins)``.
    """
    n = len(naturals)
    if n == 0:
        return []
    if not 0 <= primary < n:
        return distribute(avail, naturals, mins, caps)
    mins = [int(m) for m in mins]
    nat = [max(int(a), m) for a, m in zip(naturals, mins)]
    p_need = max(mins[primary], min(nat[primary], int(avail * primary_share)))
    others = [i for i in range(n) if i != primary]
    o_nat = [nat[i] for i in others]
    o_min = [mins[i] for i in others]
    out = [0] * n
    rest = avail - p_need
    if rest >= sum(o_nat):
        grown = distribute(rest, o_nat, o_nat, [max(int(caps[i]), nat[i]) for i in others])
        for i, w in zip(others, grown):
            out[i] = w
        out[primary] = avail - sum(grown)                      # what the others do not use
    elif rest >= sum(o_min):
        for i, w in zip(others, distribute(rest, o_nat, o_min)):
            out[i] = w
        out[primary] = p_need
    else:
        for i in others:
            out[i] = mins[i]
        out[primary] = max(mins[primary], avail - sum(o_min))
    return out
