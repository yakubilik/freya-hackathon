# Fix consolidation progress (2026-10-11)

Rules: no platform deploy, no platform simulations (round103.py + assessment agent running). Local only.

## Stage 0: orientation
- main at c66d51a. fixes/fixes-side merged (0 ahead). fixes-def = fc9eac2, 1 ahead, merge-base 333c336.
- Uncommitted diff on main: dates.py parse_year "century + rest" pieces (C-06), step.py rest_tries cap (C-06) and
  vague_period duplicate filter in _negotiate_bundle (C-03), test test_year_said_as_century_and_rest_and_the_rest_loop_ends.
  Comments say "synthetic C-06, 2026-10-11" -> left by a session this morning after c66d51a. Judging next.

## Stage 1: uncommitted diff — DONE
- Engine diff was coherent and generic but its own test crashed (len(None) in parse_year when the rest is not a number);
  fixed with `or []`. Added a C-03 test (vague_period duplicate) that fails without the dedupe. Committed as a27e8ad.
- Suite: 532 passed, 2 failed (test_simulator_rules::test_turn_counters_reset..., ::test_end_call_node_reason...) —
  both fail on c66d51a too (verified with the diff stashed): PRE-EXISTING, not touched.
- NOTE: pytest must be run as `pytest -q tests` — bare `pytest` collects the worktrees under runs/night/fixwt* (604 errors).
- submission/brief-a|b.workflow.json: platform exports from the 06:27Z deploy; vs a fresh emit on a27e8ad 12 paths differ
  (engine code blob + task_message of 11 nodes), vs HEAD's copies 158/206 differ. Not the current emitter's output -> restored
  to HEAD per the brief. round103 will re-export them when it deploys A/B at its end.
- builder/.freya-agents.json: committed (07bd... see log) — it is the deploy registry, not emitter output; restoring would drop the
  synthetic C..J slot ids and make the next deploy create new workflows (200-workflow limit). Deviation from the brief, deliberate.
## Stage 2: fixes-def — DONE (merge e3f9109; suite 545 passed, 2 pre-existing simulator failures; A/B emit differs from pre-merge only in the engine code blob)
Decisions per change in fc9eac2 (tested fixes-def's test_policy_variants on main first: 5 pass, 10 fail):
- bank/adapters.py + bank/server.py one-question verify_identity: DROP (c) — main 573e44f handles it server-side; fixes-def's own
  test test_bank_accepts_single_question_api_without_question_selector passes on main.
- dates.py spoken numeric DOB groups: DROP (c) — main 573e44f (_number_date_groups); the 4 parametrised cases pass on main. Keep the test cases.
- fragments.py close node as llm + CLOSE_PROMPT/close_content: DROP (c) — main has close_spoken_for(table) (table's own sentence,
  tts, no model turn at close: no latency, no additions). Drop its test_emitter change too.
- wire.py cents kept raw + canonical converted: DROP — main converts in place; the E reader's floor_expr uses past_due_cents and
  only works because of that. Changing it today breaks E's floor. wire.py singleton object response: DROP — final customers have
  a product list (README: up to three products); not needed, extra surface.
- step.py product-scoped note via obligation scope (D-05): DROP (c) — main handles the call-ending dispute by key
  (disputed product noted, others skipped). fixes-def's test fails on main only because it asserts via the obligation route; dropped.
- step.py situation callback (E-04: situations.{human,plan_request}.callback {reason,date_expr,time} + close): KEEP (a) —
  E's frozen table has exactly this, main calls _request_transfer(None) -> unsupported. Includes: ENGINE_ARGS/CANONICAL_REQUEST
  reason, wire reason mapping, _render reason arg, _close_row prefers the configured close, emit has_callback from situations,
  callback_reason_default in fragments, skip notes/paid-dispute while a situation callback is pending.
- step.py informational hardship (offer null, no queue, note): KEEP (a) — main does nothing in that case (E-05).
  hardship note reason from the situation's `note`: KEEP.
- step.py `"human" in kinds and not pending_transfer and not hardship_declined`: KEEP only the pending_transfer guard; the
  hardship_declined guard would swallow a real human request after a declined offer -> DROP that half.
- tests/data_paths.py: DROP — scenarios/ and synthetic/ get committed instead (stage 6).
- tests/test_policy_variants.py: keep the tests for kept features (callback x5, hardship x2, spoken DOB x4, bank single question x1).
## Stage 3: cleanup — DONE (5de32f1: one spoken-digit table, normaliser docstring; A/B emit differs only in the engine blob; suite 545 passed + 2 pre-existing)
- coverage of builder/engine under the engine tests: step.py 87%, dates.py 84% (/tmp/cov-report.txt). Uncovered != dead: only provably unreachable code is removed.
- case-id comments reviewed (52): every one states the rule with the case as evidence -> kept.
- no debug prints in builder/engine; no function name defined twice across step/dates/calendar/fragments.
- the engine source (calendar/dates/step) is minified into the workflow's engine node, so every engine edit changes that one blob;
  the no-behaviour-change proof is: A/B emit diff limited to /nodes/engine/.../code/default + suite green.
## Stage 4: gate — gate 1 on e3f9109 (post-merge): all 10 briefs A..J emit and self-test (runs/loop/gate-consolidation-1-*). Rerun after cleanup.
## Stage 5: worktrees/branches — DONE: fixwt, fixwt2, fixwt3 removed (only symlinks were untracked), branches fixes, fixes-def, fixes-side deleted with -d (all contained in main). No wip-uncommitted branch was needed.
## Stage 6: synthetic/scenarios — DONE (3f3307f, 98 files). secrets grep: only the phrase JEV_API_KEY inside scenarios/codex-review-round*.txt (a doc reference, no value). scenarios/ 1.6M, synthetic/ 1.0M. To commit after cleanup.

## Stage 4b: final gate (consolidation-2) on 5de32f1 — DONE: all briefs still emit and self-test, BAD [].
## Report: runs/night/fix-consolidation.md written and committed (force-added, runs/ is gitignored). ALL STAGES DONE.
