# Fix consolidation — 2026-10-11

**main = 5de32f1 (+ 3f3307f data). Suite: 545 passed, 2 failed (both pre-existing on c66d51a). Offline gate: all 10 briefs A..J emit and self-test (runs/loop/gate-consolidation-2-*).**

Run the suite as `.venv/bin/python -m pytest -q` (bare collection works again now that the worktrees are gone).

## Landed on main

- **a27e8ad** the uncommitted diff found on main, judged generic and committed after fixing its own crash (`len(None)` in parse_year) and adding a test for the C-03 part:
  - a year said as century + rest in two pieces ("19... 82", "nineteen 82", "19 eighty-two") reads as one year;
  - after two replies that never complete a partial identity answer the pieces are dropped and the whole question is asked again (no endless "the rest of the answer");
  - a vague period carried on the same turn's proposal is not counted twice as a vague answer (exact-day question is asked first).
- **be97834** builder/.freya-agents.json committed (deploy registry: A v21, B v6, synthetic C..J slots). Restoring it would have dropped the C..J slot ids and made the next deploy create new workflows. Deliberate deviation from the brief.
- **e3f9109** merge of `fixes-def` (fc9eac2), kept in part:
  - a situation entry with `callback: {reason, date_expr, time}` and a `close` row instead of a queue books the callback (synthetic E human/plan_request; main used to hit "unsupported");
  - the callback `reason` reaches the API when it has such a field; a third-party callback without a reason takes the API's neutral enum value;
  - a hardship entry with no offer and no queue says its line and notes the open items with its own note, agreed items stay (synthetic E);
  - 13 tests in tests/test_policy_variants.py.
- **5de32f1** cleanup: one spoken-digit table (step.py takes it from dates.UNITS), the free-text normaliser's docstring says codes go to parse_code. Table proven identical; A and B emits differ only in the engine code blob.
- **3f3307f** synthetic/ (briefs C..J, generator, reviews) and scenarios/ (extended set, builder, validator) committed. No keys inside.

## Dropped from fixes-def and why

- bank one-question verify (adapters/server): main 573e44f does it server-side; fixes-def's own test passes on main.
- spoken numeric date of birth in dates.py: main 573e44f has it; the 4 cases pass on main (kept as tests).
- close node as an LLM turn with CLOSE_PROMPT/close_content: main uses tts with the table's own sentence (close_spoken_for); no model turn, no latency, no additions.
- obligation-scope note on a call-ending situation: main handles the call-ending dispute by key (disputed product noted, others skipped).
- raw cents kept next to converted amounts in the wire normaliser: the E reader's floor expression uses `past_due_cents` and only yields units because of in-place conversion. Changing it today would break E's floor.
- single-object get_account response: final customers have a product list (README). Not needed.
- tests/data_paths.py worktree helper: the data is committed instead.
- `"human" in kinds and not hardship_declined` guard: would swallow a real human request after a declined offer. Kept only the `not pending_transfer` half.

## Cleanup

- Removed: nothing beyond the digit-table duplication. Coverage of the engine under the suite (step 87%, dates 84%) shows every uncovered block is a defensive `_unsupported` fallback, reachable by design: not dead.
- The two identity normalisers are not duplicates in function: parse_code (dates.py) reads codes, `_normalise_text_answer` (step.py) reads free text; the dispatch is one place (`_parse_answer`). Documented, not merged.
- All 52 case-id comments state the rule with the case as evidence: kept.
- Worktrees runs/night/fixwt, fixwt2, fixwt3 removed; branches fixes, fixes-def, fixes-side deleted (-d, all in main). No wip-uncommitted branch was needed.

## Wrong on main, not fixed

- tests/test_simulator_rules.py:519 and :590 fail (turn counters, end-call lifecycle tools). Pre-existing on c66d51a, simulator-only, not the engine or emitter.
- E reader: `amounts.floor_expr` in runs/synthetic/build-E/read/table.json returns cents; it works only because the wire normaliser converts cents in place. A reader fix, not done today.
- E reader: all three callback reasons in `closing.rows` use the `callback_booked` trigger; the engine now prefers the situation's `close` row, so this is covered for situation callbacks only.
- submission/brief-a|b.workflow.json were restored to HEAD (the exports on disk were from the 06:27Z deploy, 12 paths off the current emitter). round103 re-exports them when it deploys A/B.

## Left on branches / untracked

- No fix branches remain. `ustabasi/195-...` untouched.
- Untracked, left alone: kit/build-the-builder/{.freya-agents.json,.personas.json,out,results,traces}, submission/{brief,d-brief..j-joined}.workflow.json (synthetic exports).
- Appeared mid-session from another process (the assessment agent, 11:45 local): `M tools/run_extended.py` (--cases/--reps flags), `?? tools/gate.py`, `?? tools/offline_gate.py`. Not mine, not touched, not committed.
- Also from the other process, after the data commit: `M synthetic/MANIFEST.md` (11:47 local; describes a test clean-up keeping only D and I in the platform loop with 30 cases each, and tools/offline_gate.py). Not mine, not committed; whoever owns that work commits it with the new cases.
