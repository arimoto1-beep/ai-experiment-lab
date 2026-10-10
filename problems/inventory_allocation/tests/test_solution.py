"""採点専用。期待値は仕様から固定し、参照実装には依存しない。"""

from copy import deepcopy

import pytest

from solution import allocate_orders


def order(identifier, priority, *items):
    return {"id": identifier, "priority": priority,
            "items": [{"sku": sku, "quantity": quantity} for sku, quantity in items]}


# (識別名, 初期在庫, 注文, 受付ID, 拒否ID, 最終在庫)
NORMAL_CASES = [
    ("empty", {}, [], [], [], {}),
    ("no_orders", {"pen": 5, "pad": 0}, [], [], [], {"pen": 5, "pad": 0}),
    ("one_order", {"pen": 5}, [order("A", 0, ("pen", 2))], ["A"], [], {"pen": 3}),
    ("exact_stock", {"pen": 2}, [order("A", 0, ("pen", 2))], ["A"], [], {"pen": 0}),
    ("insufficient", {"pen": 1}, [order("A", 0, ("pen", 2))], [], ["A"], {"pen": 1}),
    ("zero_stock", {"pen": 0}, [order("A", 0, ("pen", 1))], [], ["A"], {"pen": 0}),
    ("unknown_sku", {"pen": 3}, [order("A", 0, ("pad", 1))], [], ["A"], {"pen": 3}),
    ("empty_stock", {}, [order("A", 0, ("pen", 1))], [], ["A"], {}),
    ("multiple_products", {"pen": 5, "pad": 3, "clip": 7},
     [order("A", 0, ("pen", 2), ("pad", 3))], ["A"], [], {"pen": 3, "pad": 0, "clip": 7}),
    ("priority_before_arrival", {"pen": 4},
     [order("A", 0, ("pen", 3)), order("Z", 9, ("pen", 2))], ["Z"], ["A"], {"pen": 2}),
    ("continue_after_rejection", {"pen": 3},
     [order("A", 2, ("pen", 4)), order("B", 1, ("pen", 2))], ["B"], ["A"], {"pen": 1}),
    ("case_sensitive", {"pen": 2, "Pen": 3},
     [order("a", 2, ("pen", 2)), order("A", 1, ("Pen", 1))], ["a", "A"], [], {"pen": 0, "Pen": 2}),
]

FIFO_CASES = [
    ("scarce_stock", {"pen": 3},
     [order("Z", 1, ("pen", 2)), order("A", 1, ("pen", 2))], ["Z"], ["A"], {"pen": 1}),
    ("accepted_order", {"pen": 9},
     [order("Z", 0, ("pen", 2)), order("A", 0, ("pen", 1))], ["Z", "A"], [], {"pen": 6}),
    ("rejected_order", {"pen": 0},
     [order("Z", 0, ("pen", 2)), order("A", 0, ("pen", 1))], [], ["Z", "A"], {"pen": 0}),
    ("separate_priority_groups", {"pen": 5},
     [order("Z", 1, ("pen", 2)), order("H", 2, ("pen", 1)), order("A", 1, ("pen", 2))],
     ["H", "Z", "A"], [], {"pen": 0}),
]

DUPLICATE_CASES = [
    ("enough", {"pen": 8}, [order("A", 0, ("pen", 2), ("pen", 3))], ["A"], [], {"pen": 3}),
    ("exact", {"pen": 5}, [order("A", 0, ("pen", 2), ("pen", 3))], ["A"], [], {"pen": 0}),
    ("total_exceeds_stock", {"pen": 4},
     [order("A", 0, ("pen", 2), ("pen", 3))], [], ["A"], {"pen": 4}),
    ("three_separated_lines", {"pen": 9, "pad": 3},
     [order("A", 0, ("pen", 1), ("pad", 2), ("pen", 2), ("pen", 3))],
     ["A"], [], {"pen": 3, "pad": 1}),
    ("followup_order", {"pen": 6},
     [order("A", 2, ("pen", 2), ("pen", 3)), order("B", 1, ("pen", 2))],
     ["A"], ["B"], {"pen": 1}),
]

ATOMIC_CASES = [
    ("late_shortage", {"pen": 4, "pad": 1},
     [order("A", 0, ("pen", 3), ("pad", 2))], [], ["A"], {"pen": 4, "pad": 1}),
    ("late_missing_sku", {"pen": 4},
     [order("A", 0, ("pen", 3), ("pad", 1))], [], ["A"], {"pen": 4}),
    ("third_line_shortage", {"pen": 4, "pad": 2, "clip": 0},
     [order("A", 0, ("pen", 3), ("pad", 1), ("clip", 1))],
     [], ["A"], {"pen": 4, "pad": 2, "clip": 0}),
    ("followup_uses_unspent_stock", {"pen": 4, "pad": 1},
     [order("A", 2, ("pen", 3), ("pad", 2)), order("B", 1, ("pen", 4))],
     ["B"], ["A"], {"pen": 0, "pad": 1}),
]

COMBINED_CASES = [
    ("statement_example", {"pen": 5, "pad": 2},
     [order("Z", 1, ("pen", 3)), order("A", 1, ("pen", 3)), order("H", 2, ("pad", 2))],
     ["H", "Z"], ["A"], {"pen": 2, "pad": 0}),
    ("duplicates_and_rollback", {"pen": 5, "pad": 2},
     [order("Z", 3, ("pen", 2), ("pad", 1), ("pen", 4)),
      order("A", 2, ("pen", 2), ("pen", 3)), order("B", 1, ("pad", 2))],
     ["A", "B"], ["Z"], {"pen": 0, "pad": 0}),
    ("mixed_batch", {"pen": 8, "pad": 3, "clip": 0},
     [order("Z", 1, ("pen", 2), ("pen", 2)),
      order("A", 1, ("pen", 2), ("pen", 3)),
      order("H", 3, ("pad", 2)), order("M", 2, ("pen", 3), ("clip", 1)),
      order("B", 0, ("pad", 1))],
     ["H", "Z", "B"], ["M", "A"], {"pen": 4, "pad": 0, "clip": 0}),
]


def check_case(stock, orders, accepted, rejected, remaining):
    # 各テストの入力を分離し、初期実装の入力変更が他のテストを汚さないようにする。
    result = allocate_orders(deepcopy(stock), deepcopy(orders))
    assert result == {"accepted": accepted, "rejected": rejected, "remaining": remaining}


@pytest.mark.parametrize("name,stock,orders,accepted,rejected,remaining", NORMAL_CASES,
                         ids=[case[0] for case in NORMAL_CASES])
def test_normal(name, stock, orders, accepted, rejected, remaining):
    check_case(stock, orders, accepted, rejected, remaining)


@pytest.mark.parametrize("name,stock,orders,accepted,rejected,remaining", FIFO_CASES,
                         ids=[case[0] for case in FIFO_CASES])
def test_fifo(name, stock, orders, accepted, rejected, remaining):
    check_case(stock, orders, accepted, rejected, remaining)


@pytest.mark.parametrize("name,stock,orders,accepted,rejected,remaining", DUPLICATE_CASES,
                         ids=[case[0] for case in DUPLICATE_CASES])
def test_duplicate_quantities(name, stock, orders, accepted, rejected, remaining):
    check_case(stock, orders, accepted, rejected, remaining)


@pytest.mark.parametrize("name,stock,orders,accepted,rejected,remaining", ATOMIC_CASES,
                         ids=[case[0] for case in ATOMIC_CASES])
def test_rejection_is_atomic(name, stock, orders, accepted, rejected, remaining):
    check_case(stock, orders, accepted, rejected, remaining)


@pytest.mark.parametrize("name,stock,orders,accepted,rejected,remaining", COMBINED_CASES,
                         ids=[case[0] for case in COMBINED_CASES])
def test_combined(name, stock, orders, accepted, rejected, remaining):
    check_case(stock, orders, accepted, rejected, remaining)


@pytest.mark.parametrize("shortage", [False, True], ids=["accepted", "rejected"])
def test_stock_is_unchanged(shortage):
    stock = {"pen": 4, "pad": 1}
    original = stock.copy()
    allocate_orders(stock, [order("A", 0, ("pen", 2), ("pad", 2 if shortage else 1))])
    assert stock == original


def test_orders_and_nested_items_are_unchanged():
    orders = [order("Z", 0, ("pen", 1), ("pen", 2)), order("A", 9, ("pad", 1))]
    original = deepcopy(orders)
    allocate_orders({"pen": 5, "pad": 1}, orders)
    assert orders == original


@pytest.mark.parametrize("edited", ["input", "output"])
def test_remaining_is_independent(edited):
    stock = {"pen": 4}
    result = allocate_orders(stock, [])
    if edited == "input":
        stock["pen"] = 99
        stock["new"] = 1
        assert result["remaining"] == {"pen": 4}
    else:
        result["remaining"]["pen"] = 99
        result["remaining"]["new"] = 1
        assert stock == {"pen": 4}


def test_repeated_calls_are_independent():
    stock = {"pen": 4}
    orders = [order("A", 0, ("pen", 3))]
    first = allocate_orders(stock, orders)
    second = allocate_orders(stock, orders)
    expected = {"accepted": ["A"], "rejected": [], "remaining": {"pen": 1}}
    assert first == second == expected
    second["accepted"].append("changed")
    second["remaining"]["pen"] = 77
    assert first == expected


@pytest.mark.parametrize("stock", [{"pen": 5, "pad": 2}, {"pen": 4, "pad": 2}],
                         ids=["accepted", "rejected"])
def test_line_order_does_not_change_outcome(stock):
    items = [("pen", 2), ("pad", 1), ("pen", 3)]
    accepted = stock["pen"] == 5
    expected = {"accepted": ["A"] if accepted else [], "rejected": [] if accepted else ["A"],
                "remaining": {"pen": 0, "pad": 1} if accepted else stock}
    for rotated in (items, items[::-1], items[1:] + items[:1]):
        assert allocate_orders(stock.copy(), [order("A", 0, *rotated)]) == expected
