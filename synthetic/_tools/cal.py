"""Calendar helpers for the synthetic briefs. Pure arithmetic; each brief's holidays are passed in."""
from datetime import date, datetime, timedelta

WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def d(s):
    return date.fromisoformat(s[:10])


def is_bd(x, hol):
    return x.weekday() < 5 and x not in hol


def add_bd(x, n, hol):
    """The n-th business day after x (n>=1). n=0 returns x."""
    c = x
    k = 0
    while k < n:
        c += timedelta(days=1)
        if is_bd(c, hol):
            k += 1
    return c


def add_cd(x, n):
    return x + timedelta(days=n)


def roll_fwd(x, hol):
    while not is_bd(x, hol):
        x += timedelta(days=1)
    return x


def roll_back(x, hol):
    while not is_bd(x, hol):
        x -= timedelta(days=1)
    return x


def next_bd(x, hol):
    return add_bd(x, 1, hol)


def last_bd_of_week(x, hol):
    fri = x + timedelta(days=4 - x.weekday())
    return roll_back(fri, hol)


def last_bd_of_next_week(x, hol):
    return last_bd_of_week(x + timedelta(days=7 - x.weekday()), hol)


def month_end(x):
    nxt = (x.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def last_bd_of_month(x, hol):
    return roll_back(month_end(x), hol)


def next_month_last_bd(x, hol):
    return last_bd_of_month(month_end(x) + timedelta(days=1), hol)


def bd_between(a, b, hol):
    """Business days strictly after a up to and including b."""
    n = 0
    c = a
    while c < b:
        c += timedelta(days=1)
        if is_bd(c, hol):
            n += 1
    return n


def fmt(x):
    return f"{WD[x.weekday()]} {x.isoformat()}"


def next_weekday(x, wd, following_week=False):
    """'this <wd>' = that weekday in the current Mon-Sun week; 'next <wd>' = following week."""
    monday = x - timedelta(days=x.weekday())
    t = monday + timedelta(days=wd)
    if following_week:
        t += timedelta(days=7)
    return t


if __name__ == "__main__":
    import sys
    for s in sys.argv[1:]:
        print(fmt(d(s)))
