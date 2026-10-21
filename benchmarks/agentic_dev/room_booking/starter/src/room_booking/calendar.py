"""予約区間の重なり判定。"""

from .timeutil import to_minutes


def overlaps(first, second):
    return to_minutes(first["start"]) <= to_minutes(second["end"]) and to_minutes(second["start"]) <= to_minutes(first["end"])


def ordered_slots(slots):
    return sorted(slots, key=lambda slot: slot["start"])
