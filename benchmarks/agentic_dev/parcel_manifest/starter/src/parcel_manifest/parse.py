"""受付行を注文単位にまとめる。"""


def group_rows(rows):
    grouped = {}
    for row in rows:
        order_id = row["order_id"].lower()
        if order_id not in grouped:
            grouped[order_id] = {"order_id": row["order_id"], "zone": row["zone"].strip(), "weight_g": 0}
        grouped[order_id]["weight_g"] += row["weight_g"]
    return list(grouped.values())
