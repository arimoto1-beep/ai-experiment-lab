"""在庫引当の参照実装。実験対象 AI に渡さない。"""

from __future__ import annotations


def _required_quantities(items: list[dict]) -> dict[str, int]:
    required = {}
    for item in items:
        sku = item["sku"]
        required[sku] = required.get(sku, 0) + item["quantity"]
    return required


def _reserve(inventory: dict[str, int], required: dict[str, int]) -> bool:
    if any(inventory.get(sku, 0) < quantity for sku, quantity in required.items()):
        return False
    for sku, quantity in required.items():
        inventory[sku] -= quantity
    return True


def allocate_orders(stock: dict[str, int], orders: list[dict]) -> dict:
    """注文ごとの受付・拒否結果と、引当後の在庫を返す。"""
    inventory = stock.copy()
    pending = sorted(orders, key=lambda order: -order["priority"])
    accepted = []
    rejected = []

    for order in pending:
        required = _required_quantities(order["items"])
        if _reserve(inventory, required):
            accepted.append(order["id"])
        else:
            rejected.append(order["id"])

    return {"accepted": accepted, "rejected": rejected, "remaining": inventory}
