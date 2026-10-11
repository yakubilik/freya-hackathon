"""Date rules of Brief A (section 7) and Brief B (rule 3), for an arbitrary `now`.

Standard library only. Every date that appears in `extended-test-set.json` is computed here,
never by hand. The file is called brief_calendar.py so it does not shadow the standard
`calendar` module for scripts run from this directory.

Rules implemented (numbers are Brief A rule numbers):
  - business days: Monday to Friday except the bank holidays (section 7 preamble)
  - 18: band from days_late (1-7 early, 8-45 late) and the deadline (12th / 7th business day after today)
  - 19: a promise date is today or later, a business day, not after the deadline
  - 20: weekend or holiday -> next business day (if the named day is not after the deadline)
  - 22: "this <weekday>" = that weekday in the current calendar week, "next <weekday>" = in the following week
  - 30: attempt 1 proposes the last business day of this week, or of next week if today is that day
  - 6:  callback window: today or the next business day, 10:00-19:00 inclusive, later than now
"""
from datetime import date, datetime, time, timedelta

HOLIDAYS = frozenset({
    date(2026, 10, 26),
    date(2026, 11, 11),
    date(2026, 11, 26),
    date(2026, 12, 25),
    date(2027, 1, 1),
})

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}

BAND_OFFSETS = {"early": 12, "late": 7}        # rule 18: business days after today
ATTEMPTS = {"early": 1, "late": 2}             # rule 18: persuasion attempts
CALLBACK_START = time(10, 0)                   # rule 6
CALLBACK_END = time(19, 0)                     # rule 6, inclusive


def parse_now(now):
    """Accept a datetime, a date or an ISO string like '2026-10-14T11:00'."""
    if isinstance(now, datetime):
        return now
    if isinstance(now, date):
        return datetime.combine(now, time(0, 0))
    return datetime.fromisoformat(now)


def parse_date(d):
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(d)


def is_business_day(d, holidays=HOLIDAYS):
    d = parse_date(d)
    return d.weekday() < 5 and d not in holidays


def next_business_day(d, holidays=HOLIDAYS):
    """The first business day strictly after d (rule 20: 'offer the next business day')."""
    d = parse_date(d) + timedelta(days=1)
    while not is_business_day(d, holidays):
        d += timedelta(days=1)
    return d


def on_or_next_business_day(d, holidays=HOLIDAYS):
    """d itself if it is a business day, otherwise the next business day."""
    d = parse_date(d)
    return d if is_business_day(d, holidays) else next_business_day(d, holidays)


def add_business_days(d, n, holidays=HOLIDAYS):
    """The n-th business day after d (d itself is not counted, whatever kind of day it is)."""
    d = parse_date(d)
    for _ in range(n):
        d = next_business_day(d, holidays)
    return d


def band(days_late):
    """Rule 18."""
    if 1 <= days_late <= 7:
        return "early"
    if 8 <= days_late <= 45:
        return "late"
    raise ValueError(f"days_late {days_late} is outside Brief A (1 to 45)")


def attempts(days_late):
    return ATTEMPTS[band(days_late)]


def deadline(now, days_late, holidays=HOLIDAYS):
    """Rule 18: the 12th (early) or 7th (late) business day after today."""
    today = parse_now(now).date()
    return add_business_days(today, BAND_OFFSETS[band(days_late)], holidays)


def promise_date_ok(now, d, days_late, holidays=HOLIDAYS):
    """Rule 19: today or later, a business day, not after the deadline."""
    today = parse_now(now).date()
    d = parse_date(d)
    return today <= d <= deadline(now, days_late, holidays) and is_business_day(d, holidays)


def resolve_named_day(now, d, days_late, holidays=HOLIDAYS):
    """What the agent records when the customer names day d (rules 19, 20, 23).

    Returns (date, how) where how is one of:
      'accepted'      the day is valid as named
      'next_business' weekend/holiday not after the deadline -> next business day (rule 20)
      'deadline'      the day is after the deadline -> the deadline is offered (rule 23)
      'past'          before today: not a valid promise date (the brief has no rule for it)
    """
    today = parse_now(now).date()
    d = parse_date(d)
    dl = deadline(now, days_late, holidays)
    if d < today:
        return d, "past"
    if d > dl:
        return dl, "deadline"
    if not is_business_day(d, holidays):
        return next_business_day(d, holidays), "next_business"
    return d, "accepted"


def week_monday(d):
    d = parse_date(d)
    return d - timedelta(days=d.weekday())


def last_business_day_of_week(d, holidays=HOLIDAYS):
    """The last business day of the calendar week (Mon-Sun) that contains d."""
    monday = week_monday(d)
    for i in range(6, -1, -1):
        day = monday + timedelta(days=i)
        if is_business_day(day, holidays):
            return day
    raise ValueError("a week without a business day")


def last_business_day_of_next_week(d, holidays=HOLIDAYS):
    return last_business_day_of_week(week_monday(d) + timedelta(days=7), holidays)


def attempt1_date(now, holidays=HOLIDAYS):
    """Rule 30, attempt 1: the last business day of this week, or of next week if today is that day."""
    today = parse_now(now).date()
    lbd = last_business_day_of_week(today, holidays)
    if lbd == today:
        return last_business_day_of_next_week(today, holidays)
    return lbd


def attempt2_date(now, days_late, holidays=HOLIDAYS):
    """Rule 30, attempt 2 (late band only): the deadline, with the floor amount."""
    if band(days_late) != "late":
        raise ValueError("attempt 2 exists only in the late band")
    return deadline(now, days_late, holidays)


def this_weekday(now, weekday):
    """Rule 22: 'this <weekday>' is that weekday in the current calendar week (Mon-Sun). May be in the past."""
    today = parse_now(now).date()
    return week_monday(today) + timedelta(days=WEEKDAYS[weekday.lower()])


def next_weekday(now, weekday):
    """Rule 22: 'next <weekday>' is that weekday in the following calendar week."""
    today = parse_now(now).date()
    return week_monday(today) + timedelta(days=7 + WEEKDAYS[weekday.lower()])


def tomorrow(now):
    return parse_now(now).date() + timedelta(days=1)


def today(now):
    return parse_now(now).date()


def callback_dates(now, holidays=HOLIDAYS):
    """Rule 6: today or the next business day."""
    t = parse_now(now).date()
    return (t, next_business_day(t, holidays))


def callback_ok(now, d, hhmm, holidays=HOLIDAYS):
    """Rule 6: date is today or the next business day, time 10:00-19:00 inclusive, and later than now."""
    n = parse_now(now)
    d = parse_date(d)
    t = time.fromisoformat(hhmm)
    if d not in callback_dates(now, holidays):
        return False
    if not (CALLBACK_START <= t <= CALLBACK_END):
        return False
    return datetime.combine(d, t) > n


def floor_of(product):
    """Rule 25."""
    if product["type"] == "credit_card":
        return float(product["minimum_payment"])
    return float(product["instalment_amount"])


def amount_ok(product, amount):
    """Rule 27: from the floor up to the full past-due amount, both included."""
    return floor_of(product) <= float(amount) <= float(product["past_due"])


def iso(d):
    return parse_date(d).isoformat()


if __name__ == "__main__":
    NOW = "2026-10-14T11:00"
    print("now", NOW, parse_now(NOW).strftime("%A"))
    print("early deadline", deadline(NOW, 5), "late deadline", deadline(NOW, 12))
    print("attempt 1", attempt1_date(NOW), "attempt 2 (late)", attempt2_date(NOW, 12))
    print("this Friday", this_weekday(NOW, "friday"), "next Friday", next_weekday(NOW, "friday"))
    print("callback dates", callback_dates(NOW))
    for n in range(1, 13):
        print(n, add_business_days(today(NOW), n))
