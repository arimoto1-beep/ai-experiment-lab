"""予約要求の公開API。"""

from .calendar import ordered_slots, overlaps
from .timeutil import to_minutes


def schedule(existing, requests):
    calendar = {}
    for reservation in existing:
        calendar.setdefault(reservation["room"], []).append(reservation)
    accepted = []
    rejected = []
    for request in sorted(requests, key=lambda item: item["priority"]):
        room = request["room"]
        slot = {"start": request["start"], "end": request["end"]}
        if any(overlaps(slot, old) for old in calendar.get(room, [])):
            rejected.append(request["id"])
            continue
        calendar.setdefault(room, []).append(slot)
        accepted.append(request["id"])
    return {"accepted": accepted, "rejected": rejected,
            "calendar": {room: ordered_slots(slots) for room, slots in calendar.items()},
            "minutes_booked": {room: sum(to_minutes(slot["end"]) - to_minutes(slot["start"])
                                         for slot in slots) for room, slots in calendar.items()}}
