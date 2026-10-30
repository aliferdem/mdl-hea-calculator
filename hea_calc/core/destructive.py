"""The one policy for destructive result actions: when a removal needs a deliberate confirmation.

Every destructive action is undoable (Edit > Undo, ``ui/undo.py``); a confirmation is added only where a slip
would cost a lot.  Carbon's guidance (Carbon MCP, patterns "Dialogs" / danger modal) reserves a danger modal
for high-impact, hard-to-recover actions and warns that routine confirmations train users to click through.
The HEA workflow removes single results from the row menu all the time - those never ask - while clearing a
populated table discards a whole calculation.

Threshold: ``CONFIRM_AT`` = 100 results, the largest results-page size (10 / 20 / 50 / 100).  Anything up to one
full page is a "handful" the user can see on screen; more than that is a batch they cannot review at a glance.
Clearing the table always counts the whole table, whatever the visible page.
"""

from __future__ import annotations

CONFIRM_AT = 100


def needs_confirmation(count: int) -> bool:
    """True when removing ``count`` results is high impact (a danger modal first, then the undoable action)."""
    return count >= CONFIRM_AT


def describe(count: int) -> str:
    return f"{count:,} result{'s' if count != 1 else ''}"
