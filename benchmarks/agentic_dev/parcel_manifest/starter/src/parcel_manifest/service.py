"""公開API。"""

from .parse import group_rows
from .price import calculate_fee


def build_manifest(rows):
    entries = group_rows(rows)
    for entry in entries:
        entry["fee_yen"] = calculate_fee(entry["zone"], entry["weight_g"])
    return {"entries": entries, "grand_total_yen": len(entries)}
