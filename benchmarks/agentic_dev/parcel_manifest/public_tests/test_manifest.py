from copy import deepcopy

from parcel_manifest import build_manifest


def row(order_id, zone, weight_g, quantity=1):
    return {"order_id": order_id, "zone": zone, "weight_g": weight_g, "quantity": quantity}


def test_one_parcel_and_input_unchanged():
    rows = [row("One", " a ", 1001)]
    original = deepcopy(rows)
    assert build_manifest(rows) == {
        "entries": [{"order_id": "One", "zone": "A", "weight_g": 1001, "fee_yen": 800}],
        "grand_total_yen": 800,
    }
    assert rows == original


def test_repeated_order_and_quantity():
    rows = [row("x", "B", 300, 2), row("y", "C", 500), row("x", " b ", 500, 3)]
    assert build_manifest(rows) == {
        "entries": [
            {"order_id": "x", "zone": "B", "weight_g": 2100, "fee_yen": 2050},
            {"order_id": "y", "zone": "C", "weight_g": 500, "fee_yen": 900},
        ],
        "grand_total_yen": 2950,
    }
