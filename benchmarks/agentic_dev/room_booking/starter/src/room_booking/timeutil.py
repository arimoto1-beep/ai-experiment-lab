"""同一日の時刻を比較可能な分単位に変換する。"""


def to_minutes(value):
    hours, minutes = value.split(":")
    return int(hours) * 100 + int(minutes)
