"""倉庫の在庫を、優先度に従って注文に引き当てる。"""

from __future__ import annotations


def _required_quantities(items: list[dict]) -> dict[str, int]:
    required = {}
    for item in items:
        required[item["sku"]] = item["quantity"]
    return required


def _reserve(inventory: dict[str, int], required: dict[str, int]) -> bool:
    for sku, quantity in required.items():
        if inventory.get(sku, 0) < quantity:
            return False
        inventory[sku] -= quantity
    return True


def allocate_orders(stock: dict[str, int], orders: list[dict]) -> dict:
    """注文ごとの受付・拒否結果と、引当後の在庫を返す。"""
    inventory = stock
    pending = sorted(orders, key=lambda order: (-order["priority"], order["id"]))
    accepted = []
    rejected = []

    for order in pending:
        required = _required_quantities(order["items"])
        if _reserve(inventory, required):
            accepted.append(order["id"])
        else:
            rejected.append(order["id"])

    return {"accepted": accepted, "rejected": rejected, "remaining": inventory}
