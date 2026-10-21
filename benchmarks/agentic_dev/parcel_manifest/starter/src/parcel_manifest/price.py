"""送料計算。"""

RATES = {"A": 400, "B": 600, "C": 900}


def calculate_fee(zone, weight_g):
    kilograms = weight_g // 1000
    fee = kilograms * RATES[zone]
    if weight_g >= 2000:
        fee += 250
    return fee
