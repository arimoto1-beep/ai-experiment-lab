from copy import deepcopy

from room_booking import schedule


def booking(identifier, room, start, end, priority=0):
    return {"id": identifier, "room": room, "start": start, "end": end, "priority": priority}


def test_priority_and_adjacent_times():
    existing = [{"room": "A", "start": "09:00", "end": "10:00"}]
    requests = [booking("low", "A", "10:00", "11:00", 1),
                booking("high", "A", "10:30", "11:30", 2)]
    old_existing, old_requests = deepcopy(existing), deepcopy(requests)
    assert schedule(existing, requests) == {
        "accepted": ["high"], "rejected": ["low"],
        "calendar": {"A": [{"start": "09:00", "end": "10:00"},
                           {"start": "10:30", "end": "11:30"}]},
        "minutes_booked": {"A": 120},
    }
    assert existing == old_existing and requests == old_requests


def test_distinct_rooms_and_empty_inputs():
    assert schedule([], []) == {"accepted": [], "rejected": [], "calendar": {}, "minutes_booked": {}}
    requests = [booking("A", "Red", "08:00", "09:00"),
                booking("B", "Blue", "08:00", "09:00")]
    assert schedule([], requests) == {
        "accepted": ["A", "B"], "rejected": [],
        "calendar": {"Red": [{"start": "08:00", "end": "09:00"}],
                     "Blue": [{"start": "08:00", "end": "09:00"}]},
        "minutes_booked": {"Red": 60, "Blue": 60},
    }
