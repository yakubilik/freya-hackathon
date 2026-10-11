"""Calendar core and the expression language of spec/interfaces.md section 1.

Every function is pure. Dates are datetime.date, times are datetime.time, `now` is a datetime.
A calendar is a dict: {"holidays": set of date, "business_days": set of weekday ints (0 = Monday)}.

Expression language (parse_expr / evaluate):
  arithmetic (+ - * /), comparisons (== != < <= > >=, chained), and/or/not, `a if c else b`,
  numbers, 'strings', names with dotted fields (product.past_due, customer.title, call.now),
  today, tomorrow, now, deadline, weekday names (bare `friday` is the string "friday"),
  functions: min, max, round(x, step, mode), business_days_after(anchor, n), calendar_days_after(anchor, n),
  next_business_day(d), on_or_next_business_day(d), this_weekday(w), next_weekday(w),
  last_business_day_of_week(d), last_business_day_of_next_week(d), end_of_month(d), is_business_day(d),
  in_window(t, start, end, inclusive), date('YYYY-MM-DD'), time('HH:MM'), weekday(d).
  `date - n` and `date + n` are calendar days; `deadline - n` therefore means n calendar days before the deadline.
Unparseable text raises ExprError (a mechanical failure); unevaluable raises EvalError.
"""
import re
from datetime import date, datetime, timedelta, time

WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
WEEKDAY_INDEX = dict((n, i) for i, n in enumerate(WEEKDAY_NAMES))
WEEKDAY_ABBR = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}
DEFAULT_BUSINESS_DAYS = frozenset([0, 1, 2, 3, 4])


class CalendarError(ValueError):
    pass


class ExprError(ValueError):
    """The expression text cannot be parsed."""


class EvalError(ValueError):
    """The expression parsed but cannot be evaluated in this context."""


# ---------------------------------------------------------------------------------------------
# basic parsing


def parse_now(now):
    """Accept a datetime, a date or an ISO string like '2026-10-14T11:00' (also with a space or seconds)."""
    if isinstance(now, datetime):
        return now
    if isinstance(now, date):
        return datetime.combine(now, time(0, 0))
    s = str(now).strip().replace(" ", "T")
    if len(s) == 10:
        return datetime.combine(date.fromisoformat(s), time(0, 0))
    return datetime.fromisoformat(s[:19])


def parse_date(d):
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d).strip()[:10])


def parse_time(t):
    if isinstance(t, time):
        return t
    if isinstance(t, datetime):
        return t.time()
    s = str(t).strip()
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def iso(d):
    return parse_date(d).isoformat()


def weekday_index(w):
    if isinstance(w, int):
        return w % 7
    s = str(w).strip().lower()
    if s in WEEKDAY_INDEX:
        return WEEKDAY_INDEX[s]
    if s in WEEKDAY_ABBR:
        return WEEKDAY_ABBR[s]
    raise CalendarError("unknown weekday: %r" % (w,))


def make_calendar(holidays=None, business_days=None):
    """Build a calendar dict. holidays: iterable of ISO strings or dates. business_days: weekday names or ints."""
    hol = set()
    if isinstance(holidays, str):
        holidays = [holidays]
    for h in holidays or []:
        hol.add(parse_date(h))
    if business_days is None:
        bd = set(DEFAULT_BUSINESS_DAYS)
    elif isinstance(business_days, str):
        bd = _business_days_from_text(business_days)
    else:
        bd = set(weekday_index(x) for x in business_days)
    return {"holidays": hol, "business_days": bd}


def _business_days_from_text(text):
    """'Monday to Friday', 'Mon-Sat', 'Monday, Tuesday, Thursday' -> a set of weekday ints."""
    s = text.strip().lower().replace("through", "to").replace("until", "to")
    s = re.sub(r"\s*[-\u2013]\s*", " to ", s)
    m = re.match(r"^\s*([a-z]+)\s+to\s+([a-z]+)\s*$", s)
    if m:
        a, b = weekday_index(m.group(1)), weekday_index(m.group(2))
        if a <= b:
            return set(range(a, b + 1))
        return set(range(a, 7)) | set(range(0, b + 1))
    names = [t for t in re.split(r"[,\s]+(?:and\s+)?", s) if t]
    return set(weekday_index(n) for n in names)


def calendar_from_table(table):
    """Read calendar.holidays and calendar.business_days from a rule table's parameters.
    Returns (calendar, missing_paths)."""
    params = (table or {}).get("parameters", {}) or {}
    missing = []
    hol = params.get("calendar.holidays", {})
    hol = hol.get("value") if isinstance(hol, dict) else None
    if hol is None:
        missing.append("calendar.holidays")
        hol = []
    bd = params.get("calendar.business_days", {})
    bd = bd.get("value") if isinstance(bd, dict) else None
    if bd is None:
        missing.append("calendar.business_days")
    return make_calendar(hol, bd), missing


# ---------------------------------------------------------------------------------------------
# business days


def is_business_day(d, cal):
    d = parse_date(d)
    return d.weekday() in cal["business_days"] and d not in cal["holidays"]


def next_business_day(d, cal):
    """The first business day strictly after d."""
    d = parse_date(d) + timedelta(days=1)
    guard = 0
    while not is_business_day(d, cal):
        d += timedelta(days=1)
        guard += 1
        if guard > 400:
            raise CalendarError("no business day within a year")
    return d


def on_or_next_business_day(d, cal):
    d = parse_date(d)
    return d if is_business_day(d, cal) else next_business_day(d, cal)


def business_days_after(d, n, cal):
    """The n-th business day after d; d itself is never counted, whatever kind of day it is."""
    d = parse_date(d)
    n = int(n)
    if n < 0:
        raise CalendarError("negative business day count")
    for _ in range(n):
        d = next_business_day(d, cal)
    return d


def calendar_days_after(d, n):
    return parse_date(d) + timedelta(days=int(n))


def week_monday(d):
    d = parse_date(d)
    return d - timedelta(days=d.weekday())


def this_weekday(today, w, rule="current_week"):
    """'this <weekday>'. rule 'current_week': that weekday in the Mon-Sun week containing today (may be past).
    rule 'forward': the next occurrence on or after today."""
    today = parse_date(today)
    wi = weekday_index(w)
    if rule == "forward":
        delta = (wi - today.weekday()) % 7
        return today + timedelta(days=delta)
    return week_monday(today) + timedelta(days=wi)


def next_weekday(today, w, rule="following_week"):
    """'next <weekday>'. rule 'following_week': that weekday in the week after the current one.
    rule 'forward': the next occurrence strictly after today."""
    today = parse_date(today)
    wi = weekday_index(w)
    if rule == "forward":
        delta = (wi - today.weekday()) % 7
        return today + timedelta(days=delta or 7)
    return week_monday(today) + timedelta(days=7 + wi)


def bare_weekday(today, w, rule="next_occurrence"):
    """A weekday named without this/next. 'next_occurrence': the next one strictly after today;
    'on_or_after': today counts; 'current_week': like this_weekday."""
    today = parse_date(today)
    wi = weekday_index(w)
    if rule == "current_week":
        return this_weekday(today, wi)
    delta = (wi - today.weekday()) % 7
    if rule == "on_or_after":
        return today + timedelta(days=delta)
    return today + timedelta(days=delta or 7)


def last_business_day_of_week(d, cal):
    monday = week_monday(d)
    for i in range(6, -1, -1):
        day = monday + timedelta(days=i)
        if is_business_day(day, cal):
            return day
    raise CalendarError("a week without a business day")


def last_business_day_of_next_week(d, cal):
    return last_business_day_of_week(week_monday(d) + timedelta(days=7), cal)


def end_of_month(d):
    d = parse_date(d)
    if d.month == 12:
        first_next = date(d.year + 1, 1, 1)
    else:
        first_next = date(d.year, d.month + 1, 1)
    return first_next - timedelta(days=1)


def in_window(t, start, end, inclusive=True):
    t, start, end = parse_time(t), parse_time(start), parse_time(end)
    if inclusive:
        return start <= t <= end
    return start < t < end


# ---------------------------------------------------------------------------------------------
# expression language: tokenizer


_TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>'[^']*'|\"[^\"]*\")|(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"|(?P<op>==|!=|<=|>=|[-+*/()<>,.]))"
)


def _tokenize(text):
    out = []
    pos = 0
    text = text.strip()
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise ExprError("cannot tokenize %r at %d" % (text, pos))
        pos = m.end()
        if m.group("num") is not None:
            v = m.group("num")
            out.append(("num", float(v) if "." in v else int(v)))
        elif m.group("str") is not None:
            out.append(("str", m.group("str")[1:-1]))
        elif m.group("name") is not None:
            out.append(("name", m.group("name")))
        else:
            out.append(("op", m.group("op")))
    out.append(("eof", None))
    return out


class _Parser(object):
    def __init__(self, text):
        self.text = text
        self.toks = _tokenize(text)
        self.i = 0

    def peek(self, kind=None, value=None):
        k, v = self.toks[self.i]
        if kind is not None and k != kind:
            return False
        if value is not None and v != value:
            return False
        return True

    def take(self, kind=None, value=None):
        if not self.peek(kind, value):
            raise ExprError("expected %s %r in %r, got %r" % (kind, value, self.text, self.toks[self.i]))
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def parse(self):
        node = self.ternary()
        if not self.peek("eof"):
            raise ExprError("trailing tokens in %r: %r" % (self.text, self.toks[self.i:]))
        return node

    def ternary(self):
        node = self.or_expr()
        if self.peek("name", "if"):
            self.take()
            cond = self.or_expr()
            self.take("name", "else")
            other = self.ternary()
            return ("if", cond, node, other)
        return node

    def or_expr(self):
        node = self.and_expr()
        while self.peek("name", "or"):
            self.take()
            node = ("or", node, self.and_expr())
        return node

    def and_expr(self):
        node = self.not_expr()
        while self.peek("name", "and"):
            self.take()
            node = ("and", node, self.not_expr())
        return node

    def not_expr(self):
        if self.peek("name", "not"):
            self.take()
            return ("not", self.not_expr())
        return self.cmp()

    def cmp(self):
        node = self.arith()
        ops = []
        while self.peek("op") and self.toks[self.i][1] in ("==", "!=", "<", "<=", ">", ">="):
            op = self.take()[1]
            ops.append((op, self.arith()))
        if ops:
            return ("cmp", node, ops)
        return node

    def arith(self):
        node = self.term()
        while self.peek("op", "+") or self.peek("op", "-"):
            op = self.take()[1]
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.peek("op", "*") or self.peek("op", "/"):
            op = self.take()[1]
            node = ("bin", op, node, self.factor())
        return node

    def factor(self):
        if self.peek("op", "-"):
            self.take()
            return ("neg", self.factor())
        if self.peek("op", "+"):
            self.take()
            return self.factor()
        return self.atom()

    def atom(self):
        if self.peek("num"):
            return ("num", self.take()[1])
        if self.peek("str"):
            return ("str", self.take()[1])
        if self.peek("op", "("):
            self.take()
            node = self.ternary()
            self.take("op", ")")
            return node
        if self.peek("name"):
            name = self.take()[1]
            if name in ("if", "else", "and", "or", "not"):
                raise ExprError("unexpected keyword %r in %r" % (name, self.text))
            if self.peek("op", "("):
                self.take()
                args = []
                if not self.peek("op", ")"):
                    args.append(self.ternary())
                    while self.peek("op", ","):
                        self.take()
                        args.append(self.ternary())
                self.take("op", ")")
                return ("call", name, args)
            path = [name]
            while self.peek("op", "."):
                self.take()
                path.append(self.take("name")[1])
            return ("name", path)
        raise ExprError("unexpected token %r in %r" % (self.toks[self.i], self.text))


def parse_expr(text):
    """Parse an expression into an AST (nested tuples). Raises ExprError on anything unparseable."""
    if text is None or str(text).strip() == "":
        raise ExprError("empty expression")
    return _Parser(str(text)).parse()


# ---------------------------------------------------------------------------------------------
# expression language: evaluation


def _cal_of(ctx):
    cal = ctx.get("cal")
    if cal is None:
        raise EvalError("no calendar in context")
    return cal


def _today(ctx):
    now = ctx.get("now")
    if now is None:
        raise EvalError("no `now` in context")
    return parse_now(now).date()


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return parse_date(v)
        except ValueError:
            raise EvalError("not a date: %r" % (v,))
    raise EvalError("not a date: %r" % (v,))


def _num(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v) if "." in v else int(v)
        except ValueError:
            raise EvalError("not a number: %r" % (v,))
    raise EvalError("not a number: %r" % (v,))


def _round(x, step, mode="nearest"):
    x = _num(x)
    step = _num(step)
    if step == 0:
        raise EvalError("round step 0")
    q = x / step
    if mode == "up":
        import_floor = int(q)
        r = import_floor if import_floor == q else (import_floor + 1 if q > 0 else import_floor)
    elif mode == "down":
        r = int(q) if q >= 0 or int(q) == q else int(q) - 1
    else:
        r = int(q + 0.5) if q >= 0 else -int(-q + 0.5)
    out = r * step
    return int(out) if float(out).is_integer() else out


def _lookup(ctx, path):
    head = path[0]
    rules = ctx.get("rules") or {}
    if head == "today":
        v = _today(ctx)
    elif head == "tomorrow":
        v = _today(ctx) + timedelta(days=1)
    elif head == "now":
        v = parse_now(ctx["now"]) if ctx.get("now") is not None else None
        if v is None:
            raise EvalError("no `now` in context")
    elif head == "deadline":
        v = ctx.get("deadline")
        if v is None:
            raise EvalError("`deadline` is not available here")
        v = _as_date(v)
    elif head in ("true", "True"):
        v = True
    elif head in ("false", "False"):
        v = False
    elif head in ("none", "None", "null"):
        v = None
    elif head in ctx and head not in ("cal", "rules"):
        v = ctx[head]
    elif head in WEEKDAY_INDEX:
        v = head
    else:
        raise EvalError("unknown name %r" % (head,))
    for p in path[1:]:
        if isinstance(v, dict):
            if p not in v:
                raise EvalError("missing field %r on %r" % (p, path[0]))
            v = v[p]
        else:
            raise EvalError("cannot read field %r of %r" % (p, path[0]))
    if isinstance(v, str) and len(path) > 1 and re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        return parse_date(v)
    return v


def _call(ctx, name, args):
    cal = ctx.get("cal")
    rules = ctx.get("rules") or {}
    n = len(args)
    if name in ("min", "max"):
        # dates compare as dates ("min(business_days_after(today, 3), deadline)": a persuasion date is never after the
        # deadline, synthetic I/J 2026-10-11), numbers as numbers
        vals = list(args)
        if any(isinstance(a, date) or (isinstance(a, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", a.strip())) for a in vals):
            vals = [_as_date(a) for a in vals]
        else:
            vals = [_num(a) for a in vals]
        return min(vals) if name == "min" else max(vals)
    if name == "round":
        if n < 2:
            raise EvalError("round needs (x, step[, mode])")
        return _round(args[0], args[1], args[2] if n > 2 else "nearest")
    if name == "abs":
        return abs(_num(args[0]))
    if name == "business_days_after":
        return business_days_after(_as_date(args[0]), _num(args[1]), _cal_of(ctx))
    if name == "calendar_days_after":
        return calendar_days_after(_as_date(args[0]), _num(args[1]))
    if name == "next_business_day":
        return next_business_day(_as_date(args[0]), _cal_of(ctx))
    if name == "on_or_next_business_day":
        return on_or_next_business_day(_as_date(args[0]), _cal_of(ctx))
    if name == "is_business_day":
        return is_business_day(_as_date(args[0]), _cal_of(ctx))
    if name == "this_weekday":
        anchor = _as_date(args[1]) if n > 1 else _today(ctx)
        return this_weekday(anchor, args[0], rules.get("this", "current_week"))
    if name == "next_weekday":
        anchor = _as_date(args[1]) if n > 1 else _today(ctx)
        return next_weekday(anchor, args[0], rules.get("next", "following_week"))
    if name == "last_business_day_of_week":
        return last_business_day_of_week(_as_date(args[0]) if n else _today(ctx), _cal_of(ctx))
    if name == "last_business_day_of_next_week":
        return last_business_day_of_next_week(_as_date(args[0]) if n else _today(ctx), _cal_of(ctx))
    if name == "end_of_month":
        return end_of_month(_as_date(args[0]) if n else _today(ctx))
    if name == "in_window":
        return in_window(args[0], args[1], args[2], bool(args[3]) if n > 3 else True)
    if name == "date":
        return _as_date(args[0])
    if name == "time":
        return parse_time(args[0])
    if name == "weekday":
        return WEEKDAY_NAMES[_as_date(args[0]).weekday()]
    raise EvalError("unknown function %r" % (name,))


def evaluate(ast, ctx):
    """Evaluate an AST against ctx = {now, cal, product, customer, call, deadline, rules}."""
    kind = ast[0]
    if kind == "num" or kind == "str":
        return ast[1]
    if kind == "name":
        return _lookup(ctx, ast[1])
    if kind == "neg":
        return -_num(evaluate(ast[1], ctx))
    if kind == "not":
        return not evaluate(ast[1], ctx)
    if kind == "and":
        return evaluate(ast[1], ctx) and evaluate(ast[2], ctx)
    if kind == "or":
        return evaluate(ast[1], ctx) or evaluate(ast[2], ctx)
    if kind == "if":
        return evaluate(ast[2], ctx) if evaluate(ast[1], ctx) else evaluate(ast[3], ctx)
    if kind == "cmp":
        left = evaluate(ast[1], ctx)
        for op, rhs in ast[2]:
            right = evaluate(rhs, ctx)
            a, b = _coerce_pair(left, right)
            if op == "==":
                ok = a == b
            elif op == "!=":
                ok = a != b
            elif op == "<":
                ok = a < b
            elif op == "<=":
                ok = a <= b
            elif op == ">":
                ok = a > b
            else:
                ok = a >= b
            if not ok:
                return False
            left = right
        return True
    if kind == "bin":
        op, a, b = ast[1], evaluate(ast[2], ctx), evaluate(ast[3], ctx)
        if isinstance(a, date) or isinstance(b, date):
            if op == "+" and isinstance(a, date):
                return a + timedelta(days=int(_num(b)))
            if op == "+" and isinstance(b, date):
                return b + timedelta(days=int(_num(a)))
            if op == "-" and isinstance(a, date) and isinstance(b, date):
                return (a - b).days
            if op == "-" and isinstance(a, date):
                return a - timedelta(days=int(_num(b)))
            raise EvalError("bad date arithmetic %r" % (op,))
        a, b = _num(a), _num(b)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if b == 0:
            raise EvalError("division by zero")
        return a / b
    if kind == "call":
        return _call(ctx, ast[1], [evaluate(x, ctx) for x in ast[2]])
    raise EvalError("bad node %r" % (kind,))


def _coerce_pair(a, b):
    if isinstance(a, date) and isinstance(b, str):
        return a, _as_date(b)
    if isinstance(b, date) and isinstance(a, str):
        return _as_date(a), b
    if isinstance(a, (int, float)) and isinstance(b, str):
        return a, _num(b)
    if isinstance(b, (int, float)) and isinstance(a, str):
        return _num(a), b
    return a, b


def eval_expr(text, ctx):
    """parse + evaluate in one call."""
    return evaluate(parse_expr(text), ctx)
