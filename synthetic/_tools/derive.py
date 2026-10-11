"""Per-brief date rules, re-derived from each brief's text. Used by validate.py and the READMEs."""
import math
from datetime import date, timedelta
from cal import d, is_bd, add_bd, add_cd, roll_fwd, roll_back, next_bd, last_bd_of_week, last_bd_of_next_week, last_bd_of_month, next_month_last_bd, month_end, fmt

HOL = {
    "C": {d(x) for x in ["2026-11-02", "2026-12-08", "2026-12-24", "2026-12-25", "2026-12-31", "2027-01-01"]},
    "D": {d(x) for x in ["2026-10-30", "2026-12-25", "2026-12-28", "2027-01-01"]},
    "E": {d(x) for x in ["2026-11-26", "2026-11-27", "2026-12-24", "2026-12-25", "2027-01-01"]},
    "F": {d(x) for x in ["2026-11-11", "2026-12-24", "2026-12-25", "2026-12-31", "2027-01-01", "2027-01-06"]},
    "G": {d(x) for x in ["2026-11-20", "2026-12-25", "2026-12-28", "2027-01-01"]},
    "H": {d(x) for x in ["2026-10-23", "2026-12-08", "2026-12-25", "2027-01-01", "2027-01-06"]},
    "I": {d(x) for x in ["2026-10-12", "2026-11-11", "2026-11-26", "2026-11-27", "2026-12-25", "2027-01-01"]},
    "J": {d(x) for x in ["2026-10-19", "2026-12-25", "2026-12-28", "2027-01-01"]},
}


def deadline(brief, today, p):
    h = HOL[brief]
    if brief == "C":  # by overdue_amount
        a = p["overdue_amount"]
        return roll_back(add_cd(today, 10), h) if a < 500 else add_bd(today, 5, h)
    if brief == "D":  # by days_in_arrears, calendar days, roll forward
        n = p["days_in_arrears"]
        k = 14 if n <= 10 else 7 if n <= 30 else 3
        return roll_fwd(add_cd(today, k), h)
    if brief == "E":  # by past_due_cents
        return add_bd(today, 15 if p["past_due_cents"] <= 100000 else 8, h)
    if brief == "F":  # month end rule / 5th working day
        if p["days_late"] <= 15:
            left = sum(1 for i in range((month_end(today) - today).days + 1) if is_bd(today + timedelta(days=i), h))
            return last_bd_of_month(today, h) if left >= 3 else next_month_last_bd(today, h)
        return add_bd(today, 5, h)
    if brief == "G":  # memo bands
        n = p["days_in_arrears"]
        return add_bd(today, 10 if n <= 14 else 6 if n <= 60 else 3, h)
    if brief == "H":  # calendar days by past_due (memo third band), roll back
        a = p["past_due"]
        k = 14 if a <= 300 else 7 if a <= 2000 else 4
        return roll_back(add_cd(today, k), h)
    if brief == "I":  # memo bands
        n = p["days_late"]
        return add_bd(today, 10 if n <= 15 else 5 if n <= 45 else 2, h)
    if brief == "J":  # memo: mortgage 3rd bd; else by amount
        if p["kind"] == "mortgage_arrears":
            return add_bd(today, 3, h)
        return add_bd(today, 10 if p["amount_due"] <= 1000 else 4, h)
    raise KeyError(brief)


def floor(brief, p):
    if brief == "C":
        return float(math.ceil(p["overdue_amount"] * 0.25))
    if brief == "D":
        return p["minimum_due"]
    if brief == "E":
        return int(math.ceil(p["past_due_cents"] * 0.30 / 100.0)) * 100
    if brief == "F":
        return p["monthly_instalment"]
    if brief == "G":
        return float(math.ceil(p["arrears"] * 0.25))
    if brief == "H":
        return p["floor"]
    if brief == "I":
        return p["min_due"]
    if brief == "J":
        return p["minimum"]


def attempt_dates(brief, today, dl):
    """Dates the persuasion attempts propose, per brief."""
    h = HOL[brief]
    if brief == "C":
        return [dl]
    if brief == "D":
        return [next_bd(today, h), dl]
    if brief == "E":
        return []
    if brief == "F":
        return [dl]
    if brief == "G":
        w = last_bd_of_week(today, h)
        return [w if w > today else last_bd_of_next_week(today, h)]
    if brief == "H":
        return [dl, dl]
    if brief == "I":
        return [min(add_bd(today, 3, h), dl)]
    if brief == "J":
        w = last_bd_of_week(today, h)
        return [w if w > today else last_bd_of_next_week(today, h), dl]


if __name__ == "__main__":
    import sys
    b, today = sys.argv[1], d(sys.argv[2])
    h = HOL[b]
    print(b, fmt(today), "bd" if is_bd(today, h) else "NOT a business day")
    print(" next bd", fmt(next_bd(today, h)), "| last bd this week", fmt(last_bd_of_week(today, h)), "| next week", fmt(last_bd_of_next_week(today, h)))
    for k in range(1, 16):
        print("  +%2d bd %s   +%2d cal %s (back %s, fwd %s)" % (k, fmt(add_bd(today, k, h)), k, fmt(add_cd(today, k)), fmt(roll_back(add_cd(today, k), h)), fmt(roll_fwd(add_cd(today, k), h))))
