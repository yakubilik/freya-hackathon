"""Resolve what a customer said (dates, times, amounts, identity answers) into wire values.

Pure functions, standard library only. Date resolution needs `now` and a rules dict:
  rules = {"this": "current_week|forward", "next": "following_week|forward",
           "bare_weekday": "next_occurrence|on_or_after|current_week", "end_of_month": "vague|exact",
           "month_first": bool}   (numbers only, "4/28": month then day when true; day then month otherwise)
resolve_date returns {"kind": "exact|vague|none", "date": iso|None, "text": original, "how": str}.
"""
import re
from datetime import date, timedelta
from .calendar import (parse_now, parse_date, WEEKDAY_INDEX, WEEKDAY_ABBR, WEEKDAY_NAMES,
                       this_weekday, next_weekday, bare_weekday, end_of_month)

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
    "nov": 11, "dec": 12,
}

UNITS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1000, "million": 1000000}
ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20, "thirtieth": 30,
}
ORDINAL_SUFFIX = re.compile(r"^(\d{1,2})(st|nd|rd|th)$")

VAGUE_PATTERNS = [
    r"\bnext week\b", r"\bthe week after\b", r"\bweek after next\b", r"\bin a couple of weeks\b",
    r"\bnext month\b", r"\bend of (the|this|next) month\b", r"\bend of month\b", r"\bmonth end\b",
    r"\bsalary\b", r"\bpay ?day\b", r"\bwhen i get paid\b", r"\bwhen i(')?m paid\b", r"\bpayslip\b", r"\bwages?\b",
    r"\bsoon\b", r"\blater\b", r"\bin a few days\b", r"\bin a few weeks\b", r"\bsome ?time\b",
    r"\bbeginning of\b", r"\bstart of\b", r"\bmiddle of\b", r"\bmid[- ]", r"\bafter the \d", r"\bnot sure\b",
    r"\bas soon as\b", r"\bwhen i can\b", r"\bone of these days\b", r"\bthis week\b", r"\bin a week or so\b",
]


# a self-correction: the words after a marker replace what came before ("the 21st, sorry, the 20th"); "rather than"
# is a comparison, not a correction
CORRECTION_RE = re.compile(r"\b(sorry|i mean|i meant|actually|no wait|wait|correction|make that|or rather|rather(?! than)|"
                           r"scratch that|not that|let me correct|no no)\b")


def _segments(text):
    """The text split at its self-correction markers, in order, empty pieces dropped: ['200', '250'] for
    "200, I mean 250, sorry". None when the text has no marker."""
    s = (text or "").lower().replace("\u2019", "'")
    if not CORRECTION_RE.search(s):
        return None
    pieces = [p.strip(" ,.;:-") for p in CORRECTION_RE.split(s)[::2]]
    return [p for p in pieces if p]


NUMERIC_WORDS = set(UNITS) | set(TENS) | set(SCALES) | set(ORDINALS)


def _has_numeric(piece):
    s = _norm(piece)
    return bool(re.search(r"\d|%", s)) or any(t in NUMERIC_WORDS for t in s.split(" "))


def _bare_day(piece):
    """The day number when the piece is only a day ('the 21st', 'on the twenty first', '31st'), else None."""
    tokens = [t for t in _norm(piece).split(" ") if t not in ("the", "on", "of")]
    if not tokens or len(tokens) > 2:
        return None
    val, used = _ordinal_words(tokens, 0)
    if val is None or used != len(tokens) or not (1 <= val <= 31):
        return None
    if len(tokens) == 1 and not (ORDINAL_SUFFIX.match(tokens[0]) or tokens[0] in ORDINALS or tokens[0].isdigit()):
        return None
    return val


def _looks_like_day(piece):
    """The piece names a day and nothing else ('the 21st', '20 October', 'next Friday'): its number is not an amount.
    A bare cardinal ('20', 'twenty five') is an amount."""
    tokens = [t for t in _norm(piece).split(" ") if t]
    date_words = [t for t in tokens if t in MONTHS or t in WEEKDAY_INDEX or t in WEEKDAY_ABBR or
                  t in ("today", "tomorrow", "next", "this", "the", "on", "of")]
    rest = [t for t in tokens if t not in date_words]
    ordinal = any(ORDINAL_SUFFIX.match(t) or t in ORDINALS for t in tokens)
    if not rest:
        return bool(date_words)
    if not date_words and not ordinal:
        return False
    return _bare_day(" ".join(rest)) is not None


def _corrected(text):
    """The last piece of a self-corrected text, or None when there is no marker or nothing but the first piece."""
    segs = _segments(text)
    if not segs or len(segs) < 2:
        return None
    return segs[-1]


def _norm(text):
    s = (text or "").lower().strip()
    s = s.replace("\u2019", "'").replace("-", " ")
    s = re.sub(r"[^\w\s:/.'ü]", " ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)  # keep the dot only between digits ("14.03.1988", "4.50"); "1988." is a sentence end
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------------------------------------------------------------------------------------------
# number words


def words_to_int(tokens):
    """Parse a list of number-word tokens (with optional 'and') into an int. None if not a number."""
    total = 0
    current = 0
    seen = False
    for t in tokens:
        if t == "and" or t == "a":
            continue
        if t.isdigit():
            current += int(t)
            seen = True
        elif t in UNITS:
            current += UNITS[t]
            seen = True
        elif t in TENS:
            current += TENS[t]
            seen = True
        elif t == "hundred":
            current = (current or 1) * 100
            seen = True
        elif t in SCALES:
            total += (current or 1) * SCALES[t]
            current = 0
            seen = True
        else:
            return None
    if not seen:
        return None
    return total + current


def _small_groups(tokens):
    """Split tokens into groups of 'small numbers' (< 100): ['six','thirty','seven','fifty'] -> [6, 37, 50]."""
    groups = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in TENS:
            v = TENS[t]
            if i + 1 < len(tokens) and tokens[i + 1] in UNITS and UNITS[tokens[i + 1]] < 10:
                v += UNITS[tokens[i + 1]]
                i += 1
            groups.append(v)
        elif t in UNITS:
            groups.append(UNITS[t])
        elif t.isdigit() and len(t) <= 2:
            groups.append(int(t))
        else:
            return None
        i += 1
    return groups


# ---------------------------------------------------------------------------------------------
# amounts


def resolve_amount_cents(text):
    """Amount text to integer cents. None when no amount is found.
    '455', '637.50', '1,250.00', '455,50', 'four hundred and fifty-five', 'six thirty seven fifty' (637.50),
    'two hundred point five' (200.50), '455 euros', '$455'."""
    if text is None:
        return None
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return int(round(float(text) * 100))
    raw = str(text).lower()
    segs = _segments(raw)
    if segs and len(segs) > 1:
        # the last piece that carries a value wins; a piece that names a day ("sorry, the 21st") corrects the day,
        # not the amount; a piece with a number that is no amount ("actually 20 percent") withdraws the amount
        for piece in reversed(segs):
            if _looks_like_day(piece):
                continue
            c = resolve_amount_cents(piece)
            if c is not None:
                return c
            if _has_numeric(piece):
                return None
        return None
    # a percentage is a discount or a share, not an amount of money ("a twenty percent discount", "20%": platform EXT-042)
    if re.search(r"\bper ?cent\b|%", raw):
        return None
    # digits first, on the raw text so that "1,250.00" and "455,50" keep their separators; "1.250,00" is the European form
    m = re.search(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+)(?:,(\d{1,2}))?(?!\d|[.,]\d|(?:st|nd|rd|th)\b)", raw)
    if m:
        whole = m.group(1).replace(".", "")
        frac = m.group(2) or ""
        return int(whole) * 100 + (int(frac.ljust(2, "0")) if frac else 0)
    m = re.search(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+|\d+)(?:[.,](\d{1,2}))?(?!\d|,\d|(?:st|nd|rd|th)\b)", raw)   # "the 21st" is a day
    if m:
        whole = m.group(1).replace(",", "")
        frac = m.group(2) or ""
        cents = int(whole) * 100 + (int(frac.ljust(2, "0")) if frac else 0)
        return cents
    s = _norm(raw)
    s = re.sub(r"\b(euros?|eur|dollars?|usd|pounds?|gbp|bucks|quid)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = [t for t in s.split(" ") if t]
    if not tokens:
        return None
    # drop leading words such as "about", "around", "pay", "the"
    numwords = set(UNITS) | set(TENS) | set(SCALES) | set(["and", "point", "dot", "cents", "cent", "a"])
    value_words = set(UNITS) | set(TENS) | set(SCALES)
    day_context = set(MONTHS) | set(WEEKDAY_INDEX) | set(["the", "on", "of"])
    start = 0
    run = None
    while start < len(tokens):
        if tokens[start] not in value_words:
            start += 1
            continue
        end = len(tokens)
        for i in range(start, len(tokens)):
            if tokens[i] not in numwords:
                end = i
                break
        # a run of number words that is a day, not an amount: followed by an ordinal word ("twenty third"), or next to
        # a month or a weekday ("October twenty third", "the twenty second of October"; platform B EXT-116, 2026-10-11)
        after = tokens[end] if end < len(tokens) else ""
        before = tokens[start - 1] if start > 0 else ""
        after2 = tokens[end + 1] if end + 1 < len(tokens) else ""
        is_day = after in ORDINALS or bool(ORDINAL_SUFFIX.match(after)) or before in MONTHS or before in WEEKDAY_INDEX \
            or after in MONTHS or (after == "of" and after2 in MONTHS) or (before in ("the", "on") and after in MONTHS)
        if not is_day:
            run = tokens[start:end]
            break
        start = end + 1
    if run is None:
        return None
    tokens = run
    while tokens and tokens[-1] in ("and", "a"):
        tokens.pop()
    if not tokens:
        return None
    # "x point y z" / "x and y cents"
    if "point" in tokens or "dot" in tokens:
        idx = tokens.index("point") if "point" in tokens else tokens.index("dot")
        whole = words_to_int(tokens[:idx])
        frac_tokens = [t for t in tokens[idx + 1:] if t not in ("cents", "cent")]
        if whole is None:
            return None
        digits = ""
        groups = _small_groups(frac_tokens)
        if groups is None:
            return None
        for g in groups:
            digits += str(g) if len(groups) > 1 and g < 10 else str(g)
        frac = (digits + "00")[:2] if digits else "00"
        return whole * 100 + int(frac)
    if "cents" in tokens or "cent" in tokens:
        idx = tokens.index("cents") if "cents" in tokens else tokens.index("cent")
        before = tokens[:idx]
        # split at the last 'and'
        if "and" in before:
            j = len(before) - 1 - before[::-1].index("and")
            whole = words_to_int(before[:j])
            cents = words_to_int(before[j + 1:])
            if whole is not None and cents is not None:
                return whole * 100 + cents
        cents = words_to_int(before)
        return cents if cents is not None else None
    has_scale = any(t in SCALES for t in tokens)
    if has_scale:
        v = words_to_int(tokens)
        return None if v is None else v * 100
    groups = _small_groups([t for t in tokens if t != "and"])
    if not groups:
        return None
    if len(groups) == 1:
        return groups[0] * 100
    if len(groups) == 2:
        a, b = groups
        if a < 10:
            # "four fifty" -> 450
            return (a * 100 + b) * 100
        if b >= 10:
            # "twenty two fifty" -> 22.50
            return a * 100 + b
        return (a * 100 + b) * 100
    # three or more groups: last group is cents, the rest read as digits ("six thirty seven fifty" -> 637.50)
    digits = ""
    for g in groups[:-1]:
        digits += str(g)
    return int(digits) * 100 + groups[-1]


def resolve_amount(text):
    """Amount text to Decimal (exact cents). None when no amount is found."""
    cents = resolve_amount_cents(text)
    if cents is None:
        return None
    from decimal import Decimal
    return Decimal(cents) / Decimal(100)


def cents_to_number(cents):
    """Integer cents to a JSON number with at most two decimals (420 -> 420, 63750 -> 637.5)."""
    if cents % 100 == 0:
        return cents // 100
    return round(cents / 100.0, 2)


def to_cents(x):
    if x is None:
        return None
    if isinstance(x, str):
        return resolve_amount_cents(x)
    return int(round(float(x) * 100))


def money_text(cents):
    whole, frac = divmod(int(cents), 100)
    if frac == 0:
        return "%d" % whole
    return "%d.%02d" % (whole, frac)


# ---------------------------------------------------------------------------------------------
# times


def resolve_time(text):
    """Time text to 'HH:MM'. None when no time is found.
    '11:00', '11', 'at 3 pm', 'around eleven', 'half past two', 'quarter to five', 'noon', '3 in the afternoon'."""
    if text is None:
        return None
    s = _norm(str(text))
    if not s:
        return None
    if re.search(r"\b(noon|midday|mid day)\b", s):
        return "12:00"
    if re.search(r"\bmidnight\b", s):
        return "00:00"
    pm = bool(re.search(r"\b(pm|p\.m|afternoon|evening|tonight|night)\b", s))
    am = bool(re.search(r"\b(am|a\.m|morning)\b", s))
    hour = None
    minute = 0
    m = re.search(r"\b(\d{1,2})[:.](\d{2})\b", s)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r"\b(half|quarter) (past|to) (\w+(?: \w+)?)\b", s)
        if m:
            h = _hour_word(m.group(3))
            if h is None:
                return None
            if m.group(1) == "half":
                hour, minute = h, 30
            elif m.group(2) == "past":
                hour, minute = h, 15
            else:
                hour, minute = h - 1, 45
        else:
            m = re.search(r"\b(\d{1,2})\s*(?:o'?clock)?\b", s)
            if m and not re.search(r"\b(st|nd|rd|th)\b", s[m.end():m.end() + 3]):
                hour = int(m.group(1))
                m2 = re.search(r"\b\d{1,2}\s+(\d{2})\b", s)
                if m2:
                    minute = int(m2.group(1))
            else:
                tokens = s.split(" ")
                for i, t in enumerate(tokens):
                    if t in UNITS and 1 <= UNITS[t] <= 12 or t in ("ten", "eleven", "twelve"):
                        hour = UNITS[t]
                        if i + 1 < len(tokens) and tokens[i + 1] in TENS:
                            minute = TENS[tokens[i + 1]]
                            if i + 2 < len(tokens) and tokens[i + 2] in UNITS and UNITS[tokens[i + 2]] < 10:
                                minute += UNITS[tokens[i + 2]]
                        elif i + 1 < len(tokens) and tokens[i + 1] == "thirty":
                            minute = 30
                        break
    if hour is None:
        return None
    if hour == 12 and am:
        hour = 0
    elif hour < 12 and pm:
        hour += 12
    elif not am and not pm and 1 <= hour <= 7:
        hour += 12          # interpretation: a bare 1-7 on a business call is the afternoon
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return "%02d:%02d" % (hour, minute)


def _hour_word(w):
    w = w.strip()
    if w.isdigit():
        return int(w)
    parts = w.split(" ")
    if parts[0] in UNITS:
        return UNITS[parts[0]]
    return None


# ---------------------------------------------------------------------------------------------
# dates


def _is_vague(s):
    for p in VAGUE_PATTERNS:
        if re.search(p, s):
            return True
    return False


def _day_number(tok):
    """'26th' -> 26, 'twenty' 'sixth' handled by caller; '26' -> 26."""
    m = ORDINAL_SUFFIX.match(tok)
    if m:
        return int(m.group(1))
    if tok.isdigit() and 1 <= int(tok) <= 31:
        return int(tok)
    if tok in ORDINALS:
        return ORDINALS[tok]
    return None


def _ordinal_words(tokens, i):
    """Read an ordinal at tokens[i]: 'twenty sixth' -> (26, 2 tokens), 'sixth' -> (6, 1)."""
    t = tokens[i]
    if t in TENS and i + 1 < len(tokens) and tokens[i + 1] in ORDINALS and ORDINALS[tokens[i + 1]] < 10:
        return TENS[t] + ORDINALS[tokens[i + 1]], 2
    if t in ORDINALS:
        return ORDINALS[t], 1
    if t in TENS and i + 1 < len(tokens) and tokens[i + 1] in UNITS and UNITS[tokens[i + 1]] < 10:
        return TENS[t] + UNITS[tokens[i + 1]], 2
    d = _day_number(t)
    if d is not None:
        return d, 1
    if t in UNITS and 1 <= UNITS[t] <= 19:
        return UNITS[t], 1
    if t in TENS and TENS[t] <= 30:
        return TENS[t], 1
    return None, 0


def _resolve_day_month(today, day, month, year):
    """Compose a date from parts; a missing month/year means the next occurrence on or after today."""
    if month is None:
        y, mth = today.year, today.month
        if day < today.day:
            mth += 1
            if mth == 13:
                mth, y = 1, y + 1
        try:
            return date(y, mth, day)
        except ValueError:
            return None
    if year is None:
        y = today.year
        try:
            d = date(y, month, day)
        except ValueError:
            return None
        if d < today - timedelta(days=0) and (today - d).days > 183:
            d = date(y + 1, month, day)
        return d
    try:
        return date(year, month, day)
    except ValueError:
        return None


_WEEKDAY_MODES = ("following_week", "forward", "current_week", "next_occurrence", "on_or_after")


def _weekday_mode(rule, default):
    """The calendar mode for a this/next/bare weekday rule. The reader writes the rule as a small expression
    ("next_weekday(w)", "this_weekday(w) if this_weekday(w) > today else next_weekday(w)") or as a mode name."""
    if not isinstance(rule, str) or not rule.strip():
        return default
    r = rule.strip()
    if r in _WEEKDAY_MODES:
        return r
    low = r.lower()
    if "> today" in low or "after today" in low or ("if" in low and "else" in low):
        return "forward"                 # the first such weekday after today, whatever the week
    if low.startswith("next_weekday"):
        return "following_week"
    if low.startswith("this_weekday"):
        return "current_week"
    if "on_or_after" in low or ">= today" in low:
        return "on_or_after"
    return default


def resolve_date(text, now, rules=None):
    """Customer date text to {"kind": "exact|vague|none", "date": iso|None, "text": text, "how": str}."""
    rules = rules or {}
    out = {"kind": "none", "date": None, "text": text, "how": ""}
    if text is None:
        return out
    today = parse_now(now).date()
    raw = str(text)
    s = _norm(raw)
    if not s:
        return out

    def exact(d, how):
        out["kind"], out["date"], out["how"] = "exact", d.isoformat(), how
        return out

    def vague(how):
        out["kind"], out["how"] = "vague", how
        return out

    segs = _segments(raw)
    if segs and len(segs) > 1:
        for i in range(len(segs) - 1, -1, -1):
            day = _bare_day(segs[i])
            if day is not None:
                # "21 November, sorry, the 20th": the day changes, the month and year said before stay; an impossible
                # day ("the 31st" of November) is no date at all, not the withdrawn one
                for earlier in segs[:i][::-1]:
                    tokens = _norm(earlier).split(" ")
                    month = next((MONTHS[t] for t in tokens if t in MONTHS), None)
                    if month is not None:
                        year = next((int(t) for t in tokens if re.match(r"^(19|20)\d{2}$", t)), None)
                        d = _resolve_day_month(today, day, month, year)
                        return exact(d, "month_name") if d else out
            r = resolve_date(segs[i], now, rules)
            if r.get("kind") == "none":
                if _has_numeric(segs[i]) or _looks_like_day(segs[i]):
                    return out      # an attempted replacement that cannot be read: ask, do not keep the withdrawn day
                continue
            r["text"] = text
            return r
        return out
    # ISO
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw)
    if m:
        try:
            return exact(date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "iso")
        except ValueError:
            return out
    # 21/07, 21/07/2026, 21.07.2026 (day first; month first when the table says the brief writes dates that way)
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\b", s)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        if rules.get("month_first"):
            day, month = month, day
        year = int(m.group(3)) if m.group(3) else None
        if year is not None and year < 100:
            year += 2000
        d = _resolve_day_month(today, day, month, year)
        return exact(d, "numeric") if d else out
    tokens = s.split(" ")
    if re.search(r"\bday after tomorrow\b", s):
        return exact(today + timedelta(days=2), "relative")
    if re.search(r"\btomorrow\b", s):
        return exact(today + timedelta(days=1), "relative")
    if re.search(r"\b(today|tonight)\b", s) or re.search(r"\bright now\b", s) or re.search(r"\bthis (morning|afternoon|evening)\b", s):
        return exact(today, "relative")
    # end of the month
    if re.search(r"\b(end|last day) of (the|this) month\b", s) or re.search(r"\bend of month\b", s) or re.search(r"\bmonth end\b", s):
        if rules.get("end_of_month") == "exact":
            return exact(end_of_month(today), "end_of_month")
        return vague("end_of_month")
    # in N days / weeks
    m = re.search(r"\bin (a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d+) (day|days|week|weeks|fortnight)\b", s)
    if m:
        n_tok = m.group(1)
        n = 1 if n_tok in ("a", "an") else (UNITS.get(n_tok) if not n_tok.isdigit() else int(n_tok))
        if n is None:
            return out
        unit = m.group(2)
        days = n * 7 if unit.startswith("week") else (14 if unit == "fortnight" else n)
        return exact(today + timedelta(days=days), "in_n")
    m = re.search(r"\b(a|one|two|three|\d) weeks? (from )?(today|now)\b", s)
    if m:
        n_tok = m.group(1)
        n = 1 if n_tok in ("a", "one") else (UNITS.get(n_tok) if not n_tok.isdigit() else int(n_tok))
        return exact(today + timedelta(days=7 * n), "in_n")
    # explicit day with month name, with or without weekday and year
    month = None
    month_pos = None
    for i, t in enumerate(tokens):
        if t in MONTHS:
            month, month_pos = MONTHS[t], i
            break
    day = None
    year = None
    if month is not None:
        # look before and after the month token for a day
        for j in list(range(month_pos - 1, max(-1, month_pos - 3), -1)) + [month_pos + 1, month_pos + 2]:
            if 0 <= j < len(tokens) and j != month_pos:
                if tokens[j] in ("of", "the", "on"):
                    continue
                val, used = _ordinal_words(tokens, j if j < month_pos or True else j)
                if j > month_pos:
                    val, used = _ordinal_words(tokens, j)
                else:
                    # read backwards: try two-token ordinal ending at j
                    val, used = (None, 0)
                    if j - 1 >= 0 and tokens[j - 1] in TENS:
                        val, used = _ordinal_words(tokens, j - 1)
                    if val is None:
                        val, used = _ordinal_words(tokens, j)
                if val is not None and 1 <= val <= 31:
                    day = val
                    break
        for t in tokens:
            if re.match(r"^(19|20)\d{2}$", t):
                year = int(t)
        if day is None:
            # "October" alone or "in October": vague
            return vague("month_only")
        d = _resolve_day_month(today, day, month, year)
        return exact(d, "month_name") if d else out
    # weekday handling
    wd = None
    wd_pos = None
    for i, t in enumerate(tokens):
        if t in WEEKDAY_INDEX or t in WEEKDAY_ABBR:
            wd = WEEKDAY_INDEX.get(t, WEEKDAY_ABBR.get(t))
            wd_pos = i
            break
    # ordinal day without month: "the 26th", "Monday the 26th", "on the twenty sixth"
    for i, t in enumerate(tokens):
        if i == wd_pos:
            continue
        val, used = _ordinal_words(tokens, i)
        if val is not None and 1 <= val <= 31 and (ORDINAL_SUFFIX.match(t) or t in ORDINALS or
                                                    (t in TENS and used == 2) or
                                                    (i > 0 and tokens[i - 1] in ("the", "on"))):
            d = _resolve_day_month(today, val, None, None)
            if d:
                return exact(d, "ordinal_day")
    if wd is not None:
        prev = tokens[wd_pos - 1] if wd_pos > 0 else ""
        if prev == "next" or (wd_pos > 1 and tokens[wd_pos - 2] == "next" and prev in ("on",)):
            return exact(next_weekday(today, wd, _weekday_mode(rules.get("next"), "following_week")), "next_weekday")
        if prev == "this" or (wd_pos > 1 and tokens[wd_pos - 2] == "this"):
            return exact(this_weekday(today, wd, _weekday_mode(rules.get("this"), "current_week")), "this_weekday")
        if re.search(r"\b(a week on|week on)\b", s):
            return exact(bare_weekday(today, wd, _weekday_mode(rules.get("bare_weekday"), "next_occurrence")) + timedelta(days=7), "week_on_weekday")
        if re.search(r"\bthe week after next\b", s):
            return exact(next_weekday(today, wd, _weekday_mode(rules.get("next"), "following_week")) + timedelta(days=7), "weekday_after_next")
        return exact(bare_weekday(today, wd, _weekday_mode(rules.get("bare_weekday"), "next_occurrence")), "bare_weekday")
    if _is_vague(s):
        return vague("period")
    return out


# ---------------------------------------------------------------------------------------------
# identity answers


def _numeric_groups_for_date(tokens):
    """[14, 3, 88] for 'fourteen oh three eighty eight', [14, 3, 1988] for 'fourteen three nineteen eighty eight'; None
    when a token is not a number word, a digit string, 'oh'/'zero', 'and' or an ordinal day ('fourteenth')."""
    toks = ["zero" if t in ("oh", "o", "nought") else t for t in tokens if t not in ("and", "the", "of")]
    toks = [str(ORDINALS[t]) if t in ORDINALS else t for t in toks]
    toks = [m.group(1) if (m := ORDINAL_SUFFIX.match(t)) else t for t in toks]
    if not toks or not all(t in UNITS or t in TENS or t == "zero" or t == "hundred" or t.isdigit() for t in toks):
        return None
    span = _year_in_words_span(toks)
    year = None
    if span:
        year, a, b = span
        toks = toks[:a] + toks[b:]
    groups = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "zero":
            # "oh three" -> 3, "oh" alone -> 0
            if i + 1 < len(toks) and toks[i + 1] in UNITS and UNITS[toks[i + 1]] < 10:
                groups.append(UNITS[toks[i + 1]])
                i += 2
            else:
                groups.append(0)
                i += 1
            continue
        if t.isdigit():
            groups.append(int(t))
            i += 1
            continue
        if t in TENS:
            v = TENS[t]
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            if nxt in UNITS and UNITS[nxt] < 10:
                v += UNITS[nxt]
                i += 1
            elif nxt.isdigit() and len(nxt) == 1:        # "twenty" + "first" (already 1)
                v += int(nxt)
                i += 1
            groups.append(v)
            i += 1
            continue
        if t in UNITS:
            groups.append(UNITS[t])
            i += 1
            continue
        return None
    if year is not None:
        groups.append(year)
    return groups


def parse_identity_date(text, parse_rule="day_month_year"):
    """A date of birth as said by a customer -> {"status": "complete|partial|none", "value": 'YYYY-MM-DD'|None, "parts": dict of day/month/year.
    Numbers only are read day, month, year (parse_rule 'day_month_year') or month, day, year ('month_day_year').
    The month is not range-checked for numeric input (the bank returns the day/month hint itself)."""
    res = {"status": "none", "value": None, "parts": dict()}
    if text is None:
        return res
    raw = str(text)
    segs = _segments(raw)
    if segs and len(segs) > 1:
        parts = {}
        for n, piece in enumerate(segs):
            got = parse_identity_date(piece, parse_rule)["parts"]
            if n and not got and _has_numeric(piece):
                return res          # "sorry, 19899": the replacement is unreadable, the withdrawn answer is not sent
            parts.update(got)
        res["parts"] = parts
        return _finish_dob(res)
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", raw)
    if m:
        res["parts"] = {"day": int(m.group(3)), "month": int(m.group(2)), "year": int(m.group(1))}
        return _finish_dob(res)
    s = _norm(raw)
    if not s:
        return res
    m = re.search(r"\b(\d{1,2})[/.\s](\d{1,2})[/.\s](\d{2,4})\b", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 1900 if y > 30 else 2000
        if parse_rule == "month_day_year":
            res["parts"] = {"day": b, "month": a, "year": y}
        else:
            res["parts"] = {"day": a, "month": b, "year": y}
        return _finish_dob(res)
    tokens = s.split(" ")
    # "fourteen oh three eighty-eight" / "fourteen, three, nineteen eighty-eight": day, month and year as numbers in words
    # (the kit's in_words customers, synthetic F-01 2026-10-11); nothing but number words, exactly three groups
    if not any(t in MONTHS for t in tokens):
        groups = _numeric_groups_for_date(tokens)
        if groups and len(groups) == 3:
            a, b, y = groups
            if y < 100:
                y += 1900 if y > 30 else 2000
            if parse_rule == "month_day_year":
                a, b = b, a
            if 1 <= a <= 31 and 1 <= b <= 12 and 1800 <= y <= 2100:
                res["parts"] = {"day": a, "month": b, "year": y}
                return _finish_dob(res)
    day = month = year = None
    span = _year_in_words_span(tokens)
    if span:
        # "nineteen ninety three": the year's words must not be read again as a day ("three")
        year, a, b = span
        tokens = tokens[:a] + tokens[b:]
    for i, t in enumerate(tokens):
        if t in MONTHS:
            month = MONTHS[t]
            continue
        if re.match(r"^(18|19|20)\d{2}$", t):
            year = int(t)
            continue
        if day is None:
            val, used = _ordinal_words(tokens, i)
            # "twenty" alone may start a year in words; "twenty-eighth" / "twenty eight April" (two tokens) is a day
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            nxt2 = tokens[i + 2] if i + 2 < len(tokens) else ""
            before_month = nxt in MONTHS or (nxt == "of" and nxt2 in MONTHS)
            # "nineteen"/"twenty" alone may start a year in words (the year's words are already removed above); before a
            # month name ("nineteen October", "twenty of May") or as two tokens ("twenty-eighth") it is the day
            if val is not None and 1 <= val <= 31 and (t not in ("nineteen", "twenty") or used == 2 or before_month) or ORDINAL_SUFFIX.match(t):
                if t in TENS and used == 1 and month is None:
                    # "twenty" could start a year in words; keep simple: treat as day only if an ordinal follows
                    pass
                day = val
                continue
    if year is None:
        # year in words: "nineteen eighty eight"
        yr = _year_in_words(tokens)
        if yr is not None:
            year = yr
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})\b", s)
    if m and day is None and month is None:
        if parse_rule == "month_day_year":
            month, day = int(m.group(1)), int(m.group(2))
        else:
            day, month = int(m.group(1)), int(m.group(2))
    res["parts"] = dict((k, v) for k, v in (("day", day), ("month", month), ("year", year)) if v is not None)
    return _finish_dob(res)


def _year_in_words_span(tokens):
    """(year, start, end) of a year said in words ('nineteen ninety three' -> (1993, i, i + 3)), or None."""
    for i in range(len(tokens) - 1):
        if tokens[i] == "two" and tokens[i + 1] == "thousand":
            # "two thousand", "two thousand and five", "two thousand twenty one"
            j = i + 2
            if j < len(tokens) and tokens[j] == "and":
                j += 1
            rest = _small_groups(tokens[j:j + 2])
            if rest and 0 <= rest[0] < 100:
                used = 2 if (tokens[j] in TENS and j + 1 < len(tokens) and tokens[j + 1] in UNITS and UNITS[tokens[j + 1]] < 10) else 1
                return 2000 + rest[0], i, j + used
            return 2000, i, i + 2
        if tokens[i] in ("nineteen", "twenty", "eighteen") and i + 1 < len(tokens):
            first = UNITS.get(tokens[i]) or TENS.get(tokens[i])   # "twenty" is in TENS; "twenty-eighth of April" starts here too
            rest = _small_groups(tokens[i + 1:i + 3])
            if rest and rest[0] >= 10:
                used = 2 if (tokens[i + 1] in TENS and i + 2 < len(tokens) and tokens[i + 2] in UNITS and UNITS[tokens[i + 2]] < 10) else 1
                return first * 100 + rest[0], i, i + 1 + used
            if tokens[i + 1] == "hundred":
                # "nineteen hundred", "nineteen hundred and sixty-eight" (the kit's in_words customers, synthetic C-03)
                j = i + 2
                if j < len(tokens) and tokens[j] == "and":
                    j += 1
                rest2 = _small_groups(tokens[j:j + 2])
                if rest2 and 0 <= rest2[0] < 100 and j < len(tokens):
                    used = 2 if (tokens[j] in TENS and j + 1 < len(tokens) and tokens[j + 1] in UNITS and UNITS[tokens[j + 1]] < 10) else 1
                    return first * 100 + rest2[0], i, j + used
                return first * 100, i, i + 2
    return None


def _year_in_words(tokens):
    span = _year_in_words_span(tokens)
    return span[0] if span else None


def _finish_dob(res):
    p = res["parts"]
    if "day" in p and "month" in p and "year" in p:
        res["status"] = "complete"
        res["value"] = "%04d-%02d-%02d" % (p["year"], p["month"], p["day"])
    elif p:
        res["status"] = "partial"
    return res


def parse_digits(text, n):
    """Digits said by a customer ('44 71', 'four four seven one', '4471') -> {"status", "value"}.
    Fewer than n digits is partial; more than n is 'none' (ambiguous)."""
    res = {"status": "none", "value": None}
    if text is None:
        return res
    segs = _segments(str(text))
    if segs and len(segs) > 1:
        for piece in reversed(segs):
            r = parse_digits(piece, n)
            if r["status"] != "none":
                return r
            if _has_numeric(piece):
                return res          # "sorry, 44712": the replacement is unreadable, the withdrawn answer is not sent
        return res
    s = _norm(str(text))
    digits = ""
    for t in s.split(" "):
        if t.isdigit():
            digits += t
        elif t in UNITS and UNITS[t] < 10:
            digits += str(UNITS[t])
        elif t == "double" or t == "triple":
            continue
    # handle "double four"
    tokens = s.split(" ")
    digits2 = ""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("double", "triple") and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            dgt = nxt if nxt.isdigit() and len(nxt) == 1 else (str(UNITS[nxt]) if nxt in UNITS and UNITS[nxt] < 10 else None)
            if dgt is not None:
                digits2 += dgt * (2 if t == "double" else 3)
                i += 2
                continue
        if t.isdigit():
            digits2 += t
        elif t in UNITS and UNITS[t] < 10:
            digits2 += str(UNITS[t])
        elif t in UNITS:
            digits2 += str(UNITS[t])            # "eleven" -> 11
        elif t in TENS:
            v = TENS[t]                          # "forty four" -> 44, "twenty" -> 20
            if i + 1 < len(tokens) and tokens[i + 1] in UNITS and 0 < UNITS[tokens[i + 1]] < 10:
                v += UNITS[tokens[i + 1]]
                i += 1
            digits2 += str(v)
        i += 1
    digits = digits2
    if not digits:
        return res
    if n is None:
        # a number of unknown length (a company or reference number): three digits or fewer is the first piece of a
        # number said in parts (the kit's "pieces" customers), four or more is the whole number
        res["status"], res["value"] = ("partial", digits) if len(digits) <= 3 else ("complete", digits)
        return res
    if len(digits) == n:
        res["status"], res["value"] = "complete", digits
    elif len(digits) < n:
        res["status"], res["value"] = "partial", digits
    return res


# the two halves of a two-part postcode said one at a time ("SW1A", then "2AA"): each alone is a partial answer
CODE_PARTIAL_RES = (re.compile(r"^[A-Z]{1,2}[0-9][0-9A-Z]?$"), re.compile(r"^[0-9][A-Z]{2}$"))
CODE_MIN_LEN = 3   # no postcode or reference anywhere is shorter


def _letter_token(tokens, i):
    """A single letter said as part of a code ("S W one A two A A"): next to another letter, a digit or a digit
    word, or last; not the pronoun in "I live at 4711"."""
    t = tokens[i]
    if len(t) != 1 or not t.isalpha():
        return False
    nxt = tokens[i + 1] if i + 1 < len(tokens) else None
    if nxt is None:
        return True
    nl = nxt.lower()
    return (len(nxt) == 1 and nxt.isalpha()) or nxt.isdigit() or nl in UNITS or nl in TENS or nl in ("oh", "double", "triple") \
        or any(ch.isdigit() for ch in nxt)


def parse_code(text):
    """An alphanumeric code said aloud (a postcode, a reference): spoken digits become digits ("four seven one one" ->
    4711, "double four" -> 44, "oh" -> 0), letters said one by one or written in capitals stay ("S W one A two A A"
    -> SW1A2AA, "SW1A 2AA" -> SW1A2AA), spaces and punctuation go, upper case; a self-correction keeps the last piece.
    Fewer than three characters, or one half of a two-part postcode, is a partial answer (the customer gives it in
    pieces, synthetic H-04/J-05 2026-10-11); nothing readable is 'none'."""
    res = {"status": "none", "value": None}
    if text is None:
        return res
    raw = str(text)
    segs = _segments(raw)
    if segs and len(segs) > 1:
        return parse_code(segs[-1])
    tokens = re.sub(r"[^\w\s]", " ", raw.replace("\u2019", "'").replace("-", " ")).split()
    out = ""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        low = t.lower()
        if t.isdigit():
            out += t
        elif low in ("double", "triple") and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            nl = nxt.lower()
            piece = nxt if (nxt.isdigit() and len(nxt) == 1) else (str(UNITS[nl]) if nl in UNITS and UNITS[nl] < 10
                                                                  else (nxt.upper() if len(nxt) == 1 and nxt.isalpha() else None))
            if piece is not None:
                out += piece * (2 if low == "double" else 3)
                i += 2
                continue
        elif low == "oh":
            out += "0"
        elif low in UNITS:
            out += str(UNITS[low])
        elif low in TENS:
            v = TENS[low]
            if i + 1 < len(tokens) and tokens[i + 1].lower() in UNITS and 0 < UNITS[tokens[i + 1].lower()] < 10:
                v += UNITS[tokens[i + 1].lower()]
                i += 1
            out += str(v)
        elif any(ch.isdigit() for ch in t):
            out += t.upper()                     # "SW1A2AA", "SW1A", "2AA"
        elif t.isalpha() and ((len(t) > 1 and t.isupper()) or _letter_token(tokens, i)):
            out += t.upper()                     # "SW", or letters one at a time
        i += 1
    if not out:
        return res
    if len(out) < CODE_MIN_LEN or any(rx.match(out) for rx in CODE_PARTIAL_RES) or (out.isdigit() and len(out) <= 3):
        # three digits alone is the first piece of a number said in parts ("four two seven" / "seven one nine", synthetic E)
        res["status"], res["value"] = "partial", out
    else:
        res["status"], res["value"] = "complete", out
    return res


YEAR_CENTURY_PIECES = {"eighteen": "18", "nineteen": "19", "twenty": "20", "18": "18", "19": "19", "20": "20", "two thousand": "20"}


def parse_year(text):
    """A year: '1968', 'nineteen sixty-eight', 'nineteen hundred and sixty-eight', 'one nine six eight' (digit by
    digit). A century alone ('nineteen', 'twenty') is the first piece of a year said in parts (partial; the engine asks
    for the rest and joins). A year without its century ('sixty-eight') is 'none': the brief wants the full year."""
    s = _norm(str(text or ""))
    m = re.search(r"\b((?:18|19|20)\d{2})\b", s)
    if m:
        return {"status": "complete", "value": m.group(1)}
    toks = s.split(" ")
    y = _year_in_words(toks)
    if y:
        return {"status": "complete", "value": str(y)}
    digits = [str(UNITS[t]) if t in UNITS and UNITS[t] < 10 else ("0" if t in ("oh", "o", "zero", "nought") else t) for t in toks]
    digits = [d for d in digits if d]
    if len(digits) == 4 and all(len(d) == 1 and d.isdigit() for d in digits) and digits[0] + digits[1] in ("18", "19", "20"):
        return {"status": "complete", "value": "".join(digits)}
    # "19... 82", "nineteen 82", "19 eighty-two": the century and the rest as two pieces (synthetic C-06, 2026-10-11)
    nums = [YEAR_CENTURY_PIECES.get(t, t) for t in toks if t not in ("and", "then")]
    if len(nums) == 2 and nums[0] in ("18", "19", "20"):
        rest = nums[1] if nums[1].isdigit() else None
        if rest is None:
            g = (_small_groups(_norm(nums[1]).split(" ")) if nums[1] else None) or []
            rest = str(g[0]) if len(g) == 1 else None
    elif len(nums) == 3 and nums[0] in ("18", "19", "20") and nums[1] in TENS and nums[2] in UNITS and UNITS[nums[2]] < 10:
        rest = str(TENS[nums[1]] + UNITS[nums[2]])
    else:
        rest = None
    if rest is not None and rest.isdigit() and len(rest) == 2:
        return {"status": "complete", "value": nums[0] + rest}
    core = re.sub(r"\b(it's|it s|it is|that's|that s|the year|year|of birth|is|was|in|born|i|yes)\b", " ", s)
    core = " ".join(core.split())
    if core in YEAR_CENTURY_PIECES:
        return {"status": "partial", "value": core}
    return {"status": "none", "value": None}


def format_date_words(d):
    """'Friday 16 October 2026' for read-backs."""
    d = parse_date(d)
    return "%s %d %s %d" % (WEEKDAY_NAMES[d.weekday()].capitalize(), d.day,
                            ["January", "February", "March", "April", "May", "June", "July", "August",
                             "September", "October", "November", "December"][d.month - 1], d.year)


# ---------------------------------------------------------------------------------------------
# numbers in words (for briefs that want amounts spoken in words)

_ONES_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
               "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS_WORDS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_words(n):
    """A whole number in British English words: 380 -> 'three hundred and eighty', 1240 -> 'one thousand two hundred
    and forty', 2005 -> 'two thousand and five'."""
    n = int(n)
    if n < 0:
        return "minus " + number_words(-n)
    if n < 20:
        return _ONES_WORDS[n]
    if n < 100:
        t, u = divmod(n, 10)
        return _TENS_WORDS[t] + ("-" + _ONES_WORDS[u] if u else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES_WORDS[h] + " hundred" + (" and " + number_words(r) if r else "")
    for scale, word in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= scale:
            big, r = divmod(n, scale)
            head = number_words(big) + " " + word
            if not r:
                return head
            return head + (" and " if r < 100 else " ") + number_words(r)
    return str(n)


_MINOR_UNIT = {"pounds": "pence", "euros": "cents", "dollars": "cents", "francs": "centimes", "liras": "kurus"}


def amount_words(cents, currency=""):
    """An amount spoken in words with its currency: (38000, 'euros') -> 'three hundred and eighty euros',
    (61240, 'euros') -> 'six hundred and twelve euros and forty cents'; no currency -> the number alone."""
    whole, frac = divmod(int(cents), 100)
    cur = (currency or "").strip()
    main = number_words(whole)
    if cur:
        unit = cur[:-1] if whole == 1 and cur.endswith("s") else cur
        main += " " + unit
    if frac:
        minor = _MINOR_UNIT.get(cur, "cents") if cur else ""
        main += " and " + number_words(frac) + ((" " + minor) if minor else "")
    return main
