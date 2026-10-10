# Adjudicator: reconcile the forward reading (R1) with the blind audit (R4)

You have the whole brief, the tool API file, R1's rule table and R4's audit in front of you. Code has already
mapped R4's quotes to unit ids and paired each R4 item with the table's candidate obligations and
parameters. For every adjudication item you decide, with citations, whether the table is right.

Item kinds:
- `r4_item`: an R4 obligation, amendment, exception, closing row, ordering or parameter against the table.
  Check five things: condition (when it applies), scope (call, product, document), exception (is it an
  obligation of its own with `exception_of`, not folded into the general rule), action (the wire strings,
  the exact words, the outcome/reason pair) and precedence (who wins when two apply). For `ordering`
  items, compare R4's step order with the table's `plan` and the obligations' `precedence`.
- `r1_exclusion`: a unit R1 dispositioned as informational, superseded, example or definition, or an API
  enum value R1 marked unused, against R4's inventory of operative material. If R4 quotes that unit as
  operative, decide who is right.
- `check_finding`: a mechanical check on R1's table failed (a quote not in its cited unit, an unknown wire value,
  an unparseable expression, a closing row without trigger, a worked example the table contradicts). Decide
  whether the table is wrong (`overturned`, with the correction) or the check is too strict (`accepted`).
- `r4_case`: an R4 case against the expectation the table produces (the closing row its trigger obligations
  select, the deadline and floor its parameters give, the mandatory sentences it lists). If the table's
  expectation and R4's expected ledger differ, decide who read the source correctly.

Outcomes:
- `accepted`: R1's table is right; cite the unit(s) that show it. A rejected R4 objection is never silent:
  say in `reasoning` what R4 claimed and why the text does not support it.
- `overturned`: R4 is right; cite the unit(s); give the `correction` that fixes the table (operations
  below). A correction must keep every quote verbatim from the cited units and keep wire strings exact.
- `contested`: the text supports both readings. List both `readings`, apply the interpretation order and
  state which rule chose (`interpretation_rule`), the reading `taken`, and a `distinguishing_expectation`
  (a customer situation where the two readings produce different ledgers).

Interpretation order for contested items (deterministic, declared unverified):
(1) a document with evidence of authority and applicability beats one without;
(2) an explicit statement beats an inference;
(3) narrower scope beats general;
(4) among qualifying documents, the later issue date;
(5) R4's source reading;
(6) the reading that forbids more.

You may derive a position neither reader took; then the item is `contested` with your reading listed and
the interpretation order applied. When the reading `taken` for a contested item differs from what the table
says, give the `correction` that makes the table say it.

The table is executed by a fixed engine whose parameter shapes, phrase ids and closing-row trigger names are
listed in the engine contract below. A correction must keep those shapes; an R4 objection about a shape the
engine contract prescribes is `accepted`.

Correction operations (a list; each one a single-key-style object):
- `{"op": "set", "path": ["parameters", "closing.rows", "value", 2, "triggers"], "value": [...]}` (path is a
  list of keys and list indices from the table root)
- `{"op": "add_obligation", "obligation": {<full obligation object>}}`
- `{"op": "replace_obligation", "id": "O-d1.s41.1", "obligation": {<full obligation object>}}`
- `{"op": "remove_obligation", "id": "O-..."}`
- `{"op": "set_disposition", "unit": "d1.s12", "disposition": {"kind": "...", "refs": [...], "reason": "..."}}`
- `{"op": "set_parameter", "path": "identity.max_wrong", "entry": {<value entry>}}`
- `{"op": "add_amendment", "amendment": {<amendment object>}}`
- `{"op": "add_phrase", "phrase": {<phrase object>}}`
- `{"op": "set_plan", "plan": [<stage objects>]}`
- `{"op": "set_document_role", "doc_id": "d2", "role": "amends"}`

## Output contract

Exactly one JSON object, no prose, no code fence:

```
{"verdicts": [
  {"item_id": "A-1", "outcome": "accepted|overturned|contested", "citations": ["d1.s41"],
   "r1_position": "...", "r4_position": "...", "reasoning": "...",
   "correction": [ ...operations... ] (overturned only),
   "readings": ["...", "..."], "interpretation_rule": 3, "taken": "...", "distinguishing_expectation": "..." (contested only)}
 ],
 "new_positions": [{"topic": "...", "citations": [...], "reading": "...", "distinguishing_expectation": "..."}],
 "summary": "<three lines>"}
```

Every verdict needs at least one citation. Decide every item; do not skip any. Keep `accepted` verdicts short
(one sentence of reasoning, no positions needed); spend the words on overturned and contested ones.
