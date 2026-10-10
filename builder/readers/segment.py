"""Lossless deterministic segmenter for a Markdown brief.

Every unit is a raw span of the source (``text == source[offset:end]``), so the concatenation of all
unit texts equals the source modulo whitespace. Unit kinds: sentence, row (table row, ``table`` points
at the header row's unit id), heading, item (list item or code-list line), quote (blockquote line),
footnote, other (structural markup: table separator rows, horizontal rules, code fences).

Documents split on top-level headings, horizontal rules and mail or memo markers (``From:``, ``To:``,
``Subject:``, ``Memo``, a date line). Unit ids are ``d<doc>.s<n>``.

``quote_to_units`` maps a free quote (as a blind auditor writes it) to unit ids by offset search over
the whitespace-normalised concatenation of unit texts; it never needs the source.
"""
from __future__ import annotations

import re
from datetime import date

HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+\S")
HR_RE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
ROW_RE = re.compile(r"^\s{0,3}\|")
SEP_ROW_RE = re.compile(r"^\s{0,3}\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
ITEM_RE = re.compile(r"^(\s*)(?:[-*+]|\d{1,3}[.)])\s+")
QUOTE_RE = re.compile(r"^\s{0,3}>")
FOOTNOTE_RE = re.compile(r"^\s{0,3}\[\^[^\]]+\]:")
FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")
COMMENT_RE = re.compile(r"^\s*<!--.*-->\s*$")
MAIL_RE = re.compile(r"^\s{0,3}(?:\*\*|__)?(From|To|Cc|Bcc|Subject|Sent|Date|Re|Ref|Reference)\s*(?:\*\*|__)?\s*:", re.I)
MEMO_RE = re.compile(r"^\s{0,3}(?:\*\*|__|#{1,6}\s+)?\s*(memo|memorandum|internal memo|circular|notice to staff)\b", re.I)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_LINE_RE = re.compile(
    r"^\s{0,3}(?:\*\*|__|_|\*)?\s*(?:dated?\s*:?\s*)?(?P<d>"
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r"\s+\d{4}"
    r"|" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"
    r"|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}"
    r")\s*(?:\*\*|__|_|\*)?\s*\.?\s*$",
    re.I,
)
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

# Sentence boundary: terminal punctuation, optional closers, whitespace, then a sentence start.
_BOUNDARY_RE = re.compile(r"[.!?]+[\"'”’)\]`]*(?P<ws>\s+)(?=[A-Z0-9\"'“‘(\[`*_])")
_ABBREV_RE = re.compile(r"(?:^|[^A-Za-z])(e\.g|i\.e|mr|ms|mrs|dr|vs|etc|cf|approx|fig|no|[A-Z])$", re.I)


def _norm_ws(s: str) -> str:
    return " ".join(s.split())


def _soft(s: str) -> str:
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = re.sub(r"[*`_~]", "", s)
    return _norm_ws(s).lower()


def _iso_date(raw: str) -> str | None:
    raw = raw.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return raw
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?\s+(\d{4})", raw)
    if m and m.group(2)[:3].lower() in MONTHS:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", raw)
    if m and m.group(1)[:3].lower() in MONTHS:
        return f"{int(m.group(3)):04d}-{MONTHS[m.group(1)[:3].lower()]:02d}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})", raw)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return date(y, int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def _date_in(line: str) -> str | None:
    m = DATE_LINE_RE.match(line)
    if m:
        return _iso_date(m.group("d")) or m.group("d")
    m = re.search(r"\d{4}-\d{2}-\d{2}", line)
    if m:
        return m.group(0)
    m = re.search(r"\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r"\s+\d{4}|" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}", line, re.I)
    if m:
        return _iso_date(m.group(0)) or m.group(0)
    return None


def split_sentences(span: str) -> list[tuple[int, int]]:
    """Sentence spans (start, end) relative to ``span``; whitespace-trimmed; lossless modulo whitespace."""
    out = []
    start = 0
    for m in _BOUNDARY_RE.finditer(span):
        before = span[: m.start()]
        # The word before the punctuation: skip abbreviations and single initials.
        tail = before[-8:]
        if _ABBREV_RE.search(tail):
            continue
        # A period inside a code span (odd number of backticks before it) does not end a sentence.
        if before.count("`") % 2 == 1:
            continue
        end = m.start("ws")
        out.append((start, end))
        start = m.end("ws")
    out.append((start, len(span)))
    trimmed = []
    for a, b in out:
        while a < b and span[a].isspace():
            a += 1
        while b > a and span[b - 1].isspace():
            b -= 1
        if a < b:
            trimmed.append((a, b))
    return trimmed


class _Builder:
    def __init__(self, source: str):
        self.source = source
        self.units: dict[str, dict] = {}
        self.documents: list[dict] = []
        self.doc = None
        self.n = 0
        self.heading_stack: list[tuple[int, str]] = []  # (level, unit_id)
        self.table_header: str | None = None

    # -- documents -------------------------------------------------------
    def _doc_has_body(self) -> bool:
        if self.doc is None:
            return False
        return any(self.units[u]["kind"] not in ("heading", "other") for u in self.doc["evidence_units"])

    def new_doc(self, kind: str, title: str | None = None, issue_date: str | None = None, force: bool = False):
        if self.doc is not None and not force and not self._doc_has_body():
            # The current document is still empty (only headings or markup): merge instead of splitting.
            if title and not self.doc.get("title"):
                self.doc["title"] = title
            if issue_date and not self.doc.get("issue_date"):
                self.doc["issue_date"] = issue_date
            if self.doc["kind"] in ("section", "other") and kind not in ("section", "other"):
                self.doc["kind"] = kind
            return
        self.doc = {"doc_id": f"d{len(self.documents) + 1}", "kind": kind, "title": title, "issue_date": issue_date, "evidence_units": []}
        self.documents.append(self.doc)
        self.n = 0
        self.heading_stack = []
        self.table_header = None

    # -- units -----------------------------------------------------------
    def add(self, offset: int, end: int, kind: str, parent: str | None = None, table: str | None = None) -> str | None:
        src = self.source
        while offset < end and src[offset].isspace():
            offset += 1
        while end > offset and src[end - 1].isspace():
            end -= 1
        if offset >= end:
            return None
        if self.doc is None:
            self.new_doc("section", force=True)
        self.n += 1
        uid = f"{self.doc['doc_id']}.s{self.n}"
        if parent is None and kind != "heading":
            parent = self.heading_stack[-1][1] if self.heading_stack else None
        self.units[uid] = {"text": src[offset:end], "doc_id": self.doc["doc_id"], "offset": offset, "end": end, "kind": kind, "parent": parent, "table": table}
        self.doc["evidence_units"].append(uid)
        return uid

    def add_heading(self, offset: int, end: int, level: int) -> str:
        while self.heading_stack and self.heading_stack[-1][0] >= level:
            self.heading_stack.pop()
        parent = self.heading_stack[-1][1] if self.heading_stack else None
        uid = self.add(offset, end, "heading", parent=parent)
        self.heading_stack.append((level, uid))
        text = self.source[offset:end].strip().lstrip("#").strip()
        if self.doc is not None and not self.doc.get("title"):
            self.doc["title"] = text
        return uid

    def add_sentences(self, offset: int, end: int, first_kind: str = "sentence"):
        span = self.source[offset:end]
        for i, (a, b) in enumerate(split_sentences(span)):
            self.add(offset + a, offset + b, first_kind if i == 0 else "sentence")


def segment(source: str) -> dict:
    """Segment a Markdown brief. Returns ``{"documents": [...], "units": {...}}``."""
    b = _Builder(source)
    lines = []
    pos = 0
    for raw in source.splitlines(keepends=True):
        lines.append((pos, raw))
        pos += len(raw)
    i = 0
    in_fence = False
    prev_marker = False  # previous non-blank line was a mail/memo/date marker (header block)
    para_start = None    # offset of an open paragraph
    para_end = None

    def flush_para():
        nonlocal para_start, para_end
        if para_start is not None:
            b.add_sentences(para_start, para_end)
            para_start = para_end = None

    while i < len(lines):
        off, raw = lines[i]
        line = raw.rstrip("\r\n")
        line_end = off + len(line)
        stripped = line.strip()
        if in_fence:
            if FENCE_RE.match(line):
                in_fence = False
                b.add(off, line_end, "other")
            elif stripped:
                b.add(off, line_end, "item")
            i += 1
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        if FENCE_RE.match(line):
            flush_para()
            in_fence = True
            if b.doc is None:
                b.new_doc("section", force=True)
            b.add(off, line_end, "other")
            prev_marker = False
            i += 1
            continue
        if HR_RE.match(line):
            flush_para()
            b.new_doc("section")
            b.add(off, line_end, "other")
            prev_marker = False
            i += 1
            continue
        hm = HEADING_RE.match(line)
        if hm:
            flush_para()
            level = len(hm.group(1))
            if level == 1:
                b.new_doc("brief", title=stripped.lstrip("#").strip())
            elif MEMO_RE.match(line):
                b.new_doc("memo", title=stripped.lstrip("#").strip())
            b.add_heading(off, line_end, level)
            prev_marker = False
            i += 1
            continue
        if COMMENT_RE.match(line):
            flush_para()
            b.add(off, line_end, "other")
            i += 1
            continue
        mail = MAIL_RE.match(line)
        memo = MEMO_RE.match(line)
        dl = DATE_LINE_RE.match(line)
        if mail or memo or dl:
            flush_para()
            if not prev_marker:
                kind = "mail" if mail else "memo" if memo else "dated"
                b.new_doc(kind)
            if mail:
                key = mail.group(1).lower()
                value = line.split(":", 1)[1].strip().strip("*_ ")
                if key == "subject" and b.doc is not None and not b.doc.get("title"):
                    b.doc["title"] = value
                if key in ("date", "sent") and b.doc is not None and not b.doc.get("issue_date"):
                    b.doc["issue_date"] = _iso_date(value) or _date_in(value) or value
            elif memo and b.doc is not None and not b.doc.get("title"):
                b.doc["title"] = stripped.strip("*_# ")
            if dl and b.doc is not None and not b.doc.get("issue_date"):
                b.doc["issue_date"] = _iso_date(dl.group("d")) or dl.group("d")
            b.add(off, line_end, "sentence")
            prev_marker = True
            i += 1
            continue
        prev_marker = False
        if ROW_RE.match(line):
            flush_para()
            if SEP_ROW_RE.match(line):
                b.add(off, line_end, "other", table=b.table_header)
            else:
                prev_is_row = i > 0 and bool(ROW_RE.match(lines[i - 1][1]))
                if b.table_header is None or not prev_is_row:
                    uid = b.add(off, line_end, "row")
                    b.units[uid]["table"] = uid
                    b.table_header = uid
                else:
                    b.add(off, line_end, "row", table=b.table_header)
            i += 1
            if i >= len(lines) or not ROW_RE.match(lines[i][1]):
                b.table_header = None
            continue
        if QUOTE_RE.match(line):
            flush_para()
            b.add(off, line_end, "quote")
            i += 1
            continue
        if FOOTNOTE_RE.match(line):
            flush_para()
            b.add(off, line_end, "footnote")
            i += 1
            continue
        im = ITEM_RE.match(line)
        if im:
            flush_para()
            indent = len(im.group(1))
            marker_end = off + im.end()
            block_end = line_end
            j = i + 1
            while j < len(lines):
                noff, nraw = lines[j]
                nline = nraw.rstrip("\r\n")
                if not nline.strip():
                    break
                if (HEADING_RE.match(nline) or ROW_RE.match(nline) or QUOTE_RE.match(nline) or FENCE_RE.match(nline)
                        or HR_RE.match(nline) or FOOTNOTE_RE.match(nline) or ITEM_RE.match(nline)):
                    break
                if len(nline) - len(nline.lstrip()) <= indent:
                    break
                block_end = noff + len(nline)
                j += 1
            # Marker plus first sentence form the item unit; the remaining sentences are sentence units.
            spans = split_sentences(source[marker_end:block_end])
            if not spans:
                b.add(off, block_end, "item")
            else:
                a0, b0 = spans[0]
                b.add(off, marker_end + b0, "item")
                for a, bb in spans[1:]:
                    b.add(marker_end + a, marker_end + bb, "sentence")
            i = j
            continue
        # Paragraph text.
        if para_start is None:
            para_start = off
        para_end = line_end
        i += 1
    flush_para()
    for d in b.documents:
        if not d.get("issue_date"):
            for uid in d["evidence_units"][:4]:
                found = _date_in(b.units[uid]["text"]) if b.units[uid]["kind"] in ("heading", "sentence") else None
                if found:
                    d["issue_date"] = found
                    break
    return {"documents": b.documents, "units": b.units}


def units_text(units: dict) -> str:
    """All unit texts in source order, joined by single spaces (for the losslessness check)."""
    return " ".join(_norm_ws(u["text"]) for _, u in sorted(units.items(), key=lambda kv: (kv[1]["offset"], kv[0])))


def lossless(source: str, units: dict) -> bool:
    return _norm_ws(source) == units_text(units)


def _concat_index(units: dict, norm):
    parts, spans, p = [], [], 0
    for uid, u in sorted(units.items(), key=lambda kv: (kv[1]["offset"], kv[0])):
        t = norm(u["text"])
        if not t:
            continue
        parts.append(t)
        spans.append((p, p + len(t), uid))
        p += len(t) + 1
    return " ".join(parts), spans


def locate_quote(text: str, units: dict) -> dict:
    """Map a quote to unit ids. Returns {units, method} with method exact|soft|partial|fuzzy|none."""
    q = _norm_ws(text)
    if not q:
        return {"units": [], "method": "none"}
    for method, norm in (("exact", _norm_ws), ("soft", _soft)):
        concat, spans = _concat_index(units, norm)
        nq = norm(q)
        if not nq:
            continue
        p = concat.find(nq)
        if p >= 0:
            qe = p + len(nq)
            return {"units": [uid for a, bb, uid in spans if a < qe and bb > p], "method": method}
    # Partial: the longest prefix and suffix windows of the quote that still match somewhere.
    concat, spans = _concat_index(units, _soft)
    sq = _soft(q)
    hits = []
    for probe in (sq[:40], sq[-40:]):
        if len(probe) >= 15:
            p = concat.find(probe)
            if p >= 0:
                hits += [uid for a, bb, uid in spans if a < p + len(probe) and bb > p]
    if hits:
        return {"units": sorted(set(hits), key=lambda u: units[u]["offset"]), "method": "partial"}
    # Fuzzy: token overlap per unit.
    qtok = {w for w in re.findall(r"[a-z0-9_]{3,}", sq)}
    if not qtok:
        return {"units": [], "method": "none"}
    best, best_score = None, 0.0
    for uid, u in units.items():
        ut = set(re.findall(r"[a-z0-9_]{3,}", _soft(u["text"])))
        if not ut:
            continue
        score = len(qtok & ut) / len(qtok)
        if score > best_score:
            best, best_score = uid, score
    if best is not None and best_score >= 0.6:
        return {"units": [best], "method": "fuzzy"}
    return {"units": [], "method": "none"}


def quote_to_units(text: str, units: dict) -> list[str]:
    """Unit ids a quote maps to by offset search (used for R4's quotes)."""
    return locate_quote(text, units)["units"]


def quote_in_units(quote: str, unit_ids: list[str], units: dict) -> str | None:
    """Verify an R1 quote against its cited units. Returns 'exact', 'soft' or None."""
    ids = [u for u in unit_ids if u in units]
    if not ids:
        return None
    ids.sort(key=lambda u: units[u]["offset"])
    joined = " ".join(units[u]["text"] for u in ids)
    q = _norm_ws(quote)
    if q and q in _norm_ws(joined):
        return "exact"
    if _soft(q) and _soft(q) in _soft(joined):
        return "soft"
    return None
