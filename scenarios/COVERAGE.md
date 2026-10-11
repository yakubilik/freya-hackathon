# Coverage of the extended practice set

155 scenarios in `extended-test-set.json`, each on the bank account of one official practice case
(`session_case`). The mock bank knows only those 13 accounts, so only what the customer does
changes. `now` is always Wednesday 2026-10-14 11:00. Every date in `expected` was computed with
`brief_calendar.py` (the self-test in `validate.py` re-derives the 13 official cases with it).

Derived values used everywhere:

| What | Value |
|---|---|
| today / tomorrow (next business day) | Wed 14 Oct / Thu 15 Oct |
| last business day of this week (rule 30, attempt 1) | Fri 16 Oct |
| "this Friday" / "next Friday" (rule 22) | 16 Oct / 23 Oct |
| late-band deadline, 7th business day (days_late 8-45) | Fri 23 Oct |
| early-band deadline, 12th business day (days_late 1-7) | Mon 2 Nov (26 Oct is a holiday) |
| callback window (rule 6) | 14 Oct after 11:00, or 15 Oct, 10:00-19:00 inclusive |

Accounts: PUB-01, 03, 07, 08 early band; PUB-02, 04, 05, 06, 09, 10 late band; PUB-10 is the only
account where `create_promise` fails on its first call (inherited `faults`). PUB-11 and PUB-12
have two late products and one early; PUB-13 one early and one late.

## Rule table

Rows generated from the `rules` field of each scenario. A rule is listed where it decides, or
visibly shapes, the expected result; incidental rules (every call has a close_call, every promise
has a text-message sentence) are listed only where a check names them.

| Rule | Scenarios | Ids |
|---|---|---|
| A1 | 16 | EXT-002, EXT-003, EXT-005, EXT-006, EXT-007, EXT-020, EXT-031, EXT-032, EXT-033, EXT-036, EXT-095, EXT-097, EXT-136, EXT-138, EXT-139, EXT-145 |
| A2 | 4 | EXT-001, EXT-004, EXT-006, EXT-007 |
| A3 | 8 | EXT-001, EXT-002, EXT-003, EXT-004, EXT-005, EXT-006, EXT-007, EXT-138 |
| A4 | 2 | EXT-004, EXT-145 |
| A5 | 14 | EXT-008, EXT-009, EXT-010, EXT-012, EXT-013, EXT-014, EXT-015, EXT-016, EXT-017, EXT-018, EXT-020, EXT-021, EXT-022, EXT-147 |
| A6 | 13 | EXT-008, EXT-009, EXT-010, EXT-011, EXT-014, EXT-015, EXT-016, EXT-017, EXT-018, EXT-019, EXT-020, EXT-147, EXT-148 |
| A7 | 7 | EXT-010, EXT-011, EXT-016, EXT-017, EXT-019, EXT-147, EXT-148 |
| A8 | 2 | EXT-012, EXT-021 |
| A9 | 2 | EXT-013, EXT-022 |
| A10 | 2 | EXT-014, EXT-015 |
| A11 | 13 | EXT-023, EXT-024, EXT-025, EXT-026, EXT-030, EXT-034, EXT-035, EXT-038, EXT-133, EXT-135, EXT-136, EXT-138, EXT-149 |
| A12 | 7 | EXT-025, EXT-026, EXT-027, EXT-028, EXT-029, EXT-037, EXT-149 |
| A13 | 3 | EXT-024, EXT-034, EXT-149 |
| A14 | 3 | EXT-027, EXT-028, EXT-029 |
| A15 | 8 | EXT-030, EXT-031, EXT-032, EXT-033, EXT-036, EXT-097, EXT-136, EXT-139 |
| A16 | 4 | EXT-023, EXT-025, EXT-037, EXT-149 |
| A17 | 4 | EXT-039, EXT-043, EXT-130, EXT-135 |
| A18 | 39 | EXT-042, EXT-045, EXT-046, EXT-047, EXT-048, EXT-049, EXT-050, EXT-051, EXT-053, EXT-054, EXT-055, EXT-058, EXT-059, EXT-060, EXT-061, EXT-063, EXT-068, EXT-069, EXT-071, EXT-072, EXT-074, EXT-076, EXT-077, EXT-078, EXT-079, EXT-107, EXT-109, EXT-110, EXT-112, EXT-114, EXT-115, EXT-116, EXT-119, EXT-123, EXT-125, EXT-126, EXT-129, EXT-150, EXT-151 |
| A19 | 22 | EXT-044, EXT-045, EXT-047, EXT-049, EXT-051, EXT-052, EXT-054, EXT-055, EXT-056, EXT-057, EXT-062, EXT-072, EXT-082, EXT-099, EXT-123, EXT-126, EXT-131, EXT-132, EXT-134, EXT-146, EXT-154, EXT-155 |
| A20 | 10 | EXT-044, EXT-045, EXT-046, EXT-047, EXT-058, EXT-059, EXT-063, EXT-100, EXT-110, EXT-125 |
| A21 | 7 | EXT-052, EXT-053, EXT-054, EXT-062, EXT-125, EXT-150, EXT-151 |
| A22 | 4 | EXT-055, EXT-056, EXT-057, EXT-154 |
| A23 | 13 | EXT-046, EXT-048, EXT-050, EXT-058, EXT-059, EXT-060, EXT-061, EXT-063, EXT-074, EXT-107, EXT-109, EXT-110, EXT-125 |
| A24 | 7 | EXT-040, EXT-064, EXT-066, EXT-067, EXT-069, EXT-070, EXT-153 |
| A25 | 25 | EXT-060, EXT-064, EXT-065, EXT-066, EXT-067, EXT-068, EXT-069, EXT-070, EXT-071, EXT-072, EXT-073, EXT-074, EXT-077, EXT-078, EXT-079, EXT-084, EXT-101, EXT-102, EXT-105, EXT-116, EXT-122, EXT-128, EXT-134, EXT-144, EXT-153 |
| A26 | 5 | EXT-069, EXT-070, EXT-071, EXT-073, EXT-128 |
| A27 | 17 | EXT-064, EXT-065, EXT-066, EXT-067, EXT-068, EXT-072, EXT-073, EXT-074, EXT-084, EXT-101, EXT-102, EXT-105, EXT-122, EXT-128, EXT-134, EXT-144, EXT-153 |
| A28 | 4 | EXT-075, EXT-080, EXT-130, EXT-137 |
| A29 | 16 | EXT-044, EXT-045, EXT-047, EXT-048, EXT-049, EXT-051, EXT-052, EXT-055, EXT-056, EXT-058, EXT-063, EXT-065, EXT-072, EXT-073, EXT-146, EXT-155 |
| A30 | 21 | EXT-042, EXT-060, EXT-061, EXT-068, EXT-069, EXT-071, EXT-075, EXT-076, EXT-077, EXT-078, EXT-079, EXT-080, EXT-098, EXT-112, EXT-114, EXT-115, EXT-116, EXT-119, EXT-129, EXT-146, EXT-150 |
| A31 | 13 | EXT-042, EXT-061, EXT-068, EXT-071, EXT-076, EXT-078, EXT-079, EXT-112, EXT-114, EXT-115, EXT-116, EXT-119, EXT-129 |
| A32 | 7 | EXT-081, EXT-082, EXT-083, EXT-084, EXT-120, EXT-121, EXT-152 |
| A33 | 4 | EXT-040, EXT-041, EXT-042, EXT-091 |
| A34 | 9 | EXT-099, EXT-100, EXT-101, EXT-102, EXT-106, EXT-132, EXT-134, EXT-140, EXT-144 |
| A35 | 7 | EXT-099, EXT-100, EXT-101, EXT-102, EXT-105, EXT-107, EXT-126 |
| A36 | 3 | EXT-092, EXT-103, EXT-104 |
| A37 | 6 | EXT-032, EXT-050, EXT-062, EXT-104, EXT-105, EXT-139 |
| A38 | 7 | EXT-001, EXT-057, EXT-104, EXT-106, EXT-131, EXT-142, EXT-154 |
| A39 | 9 | EXT-085, EXT-086, EXT-089, EXT-112, EXT-113, EXT-114, EXT-124, EXT-127, EXT-137 |
| A40 | 7 | EXT-086, EXT-087, EXT-088, EXT-090, EXT-111, EXT-114, EXT-127 |
| A41 | 6 | EXT-041, EXT-091, EXT-092, EXT-117, EXT-118, EXT-152 |
| A42 | 5 | EXT-093, EXT-094, EXT-095, EXT-096, EXT-119 |
| A43 | 2 | EXT-005, EXT-143 |
| A44 | 3 | EXT-039, EXT-043, EXT-145 |
| A45 | 3 | EXT-095, EXT-097, EXT-098 |
| A46 | 5 | EXT-092, EXT-096, EXT-118, EXT-137, EXT-152 |
| A47 | 2 | EXT-130, EXT-140 |
| B1 | 3 | EXT-108, EXT-111, EXT-115 |
| B2 | 4 | EXT-034, EXT-035, EXT-108, EXT-141 |
| B3 | 5 | EXT-109, EXT-110, EXT-123, EXT-125, EXT-151 |
| B4 | 8 | EXT-108, EXT-115, EXT-119, EXT-122, EXT-125, EXT-128, EXT-141, EXT-142 |
| B5 | 6 | EXT-112, EXT-114, EXT-115, EXT-116, EXT-119, EXT-129 |
| B6 | 3 | EXT-109, EXT-110, EXT-123 |
| B7 | 12 | EXT-034, EXT-035, EXT-108, EXT-109, EXT-117, EXT-122, EXT-126, EXT-129, EXT-140, EXT-141, EXT-142, EXT-151 |
| B8 | 10 | EXT-111, EXT-112, EXT-113, EXT-114, EXT-115, EXT-116, EXT-121, EXT-124, EXT-127, EXT-129 |
| B9 | 5 | EXT-111, EXT-112, EXT-114, EXT-124, EXT-127 |
| B10 | 4 | EXT-117, EXT-118, EXT-119, EXT-120 |
| B11 | 0 | not testable on the fixed bank, see below |
| B closing paragraph (`B-closing`) | 10 | EXT-111, EXT-112, EXT-113, EXT-114, EXT-115, EXT-116, EXT-121, EXT-124, EXT-127, EXT-129 |

### Rules that cannot be exercised on the fixed bank

- **B11** (one `create_promise` fails twice, note `service_error`) and the second half of **A37**
  (`no_promise` / `service_error`): the only injected fault is on PUB-10 (Brief A, fails once).
  No account fails twice and no Brief B account fails at all. The retry half of A37 is covered six
  times on PUB-10.
- **A22, second sentence** ("next Friday" said on a Friday): `now` is a Wednesday. The definition
  is covered (EXT-055, 056, 057), the Friday-on-Friday example is not.
- **A30, attempt 1 when today is the last business day of the week**: same reason. The calendar
  module implements it; no scenario can reach it.

## Open questions

Situations where the briefs do not clearly determine the right records. No scenario was written
for them; each describes the colliding rules and the readings. Worth asking the organizers.

1. **Hardship after a product is agreed but not yet recorded (Brief B).** Customer agrees to pay
   the card on Friday, then on the loan says she lost her job and declines the support transfer.
   A32 says "close as `no_promise` / `hardship`"; B7 says promises are read back together and
   recorded at the end; the B closing says `promise` wins whenever a promise was recorded. B10
   drops agreed-but-unrecorded promises explicitly, but only for restructuring. Reading (a): finish
   the read-back, record the card, note `hardship` on the loan, close `promise`. Reading (b): close
   `no_promise` / `hardship` at once and the card promise is never recorded. EXT-121 (hardship
   before any product is agreed) is included because there nothing is lost either way.




2. **An amount above the full past-due amount.** A27 covers "from the floor up to the full
   amount, both included". A customer who offers 500 on a 420 debt: record 420, record 500, or
   say it cannot be recorded? A33 forbids terms not in the brief; nothing says what the cap is.




3. **Third party who cannot give any time.** "I don't know when she'll be back." A7 covers only a
   day or time *offered* outside the window (ask once, then `no_callback`). Is "I don't know" the
   same as an outside offer (ask once more, then `no_callback`), or should the agent close
   `no_callback` at once, or keep asking?




4. **Partial "already paid".** "I paid half of it yesterday." A39 covers only "a payment of this
   past-due amount". Close as `paid`, or seek a promise for the rest (the agent has no figure for
   the rest, and A44 forbids inventing one), or treat it as a dispute?




5. **A bare weekday or "Friday week".** A22 defines only "this <weekday>" and
   "next <weekday>". "Friday" alone said on a Wednesday: the coming Friday, or a vague period under
   A21 (ask once for the exact day)? An exact duration such as "in two weeks" is not in doubt (28 October). Payment-date scripts in this set say "this", "next" or the date; the only bare "Friday" (EXT-017) is a callback offer, where any Friday is outside the window, and the "Friday" in EXT-132 is withdrawn in the same sentence.




6. **Third-party time with no date.** "Try at three." A6 needs a date and a time. Today if later
    than now and otherwise tomorrow, or ask which day?




7. **Dispute or "already paid" after a promise is recorded (Brief A).** A36: a recorded promise
    cannot be cancelled. A39 / A40: close `paid` / `dispute`. The table: `promise` whenever at least
    one promise was recorded, and only transfers are said to override it. `promise` or `dispute`?




8. **Confirmation by a nickname.** A3 accepts "the customer's own name", which covers "Daniel here" for Daniel Reyes (no surname is demanded). A nickname the bank does not hold ("Danny speaking") is not covered: confirmation or unclear?


9. **A single total across products (Brief B).** "I can give you 500 for all of it." No rule says
    how to split a total, or whether to treat it as "too much" per product (A26).




10. **Transfer to a human or support after a product is agreed but not recorded (Brief B).** B10
    says agreed-but-unrecorded promises are not recorded for a *restructuring* request and "on any
    transfer add no notes", but says nothing about unrecorded promises for human or support
    transfers. Drop them like restructuring, or record them first (A46: a transfer after a recorded
    promise closes as `transferred`)? EXT-119 avoids this: nothing was agreed before the request.




11. **What counts as a "clear yes" at the read-back (A34).** A34 requires "a clear yes" without a vocabulary. Clear affirmatives ("yes", "sure", "I confirm") are not in doubt; hesitant assent ("I suppose", "if you say so") is a judgment boundary the brief does not draw. No scenario depends on it: EXT-106 now uses an explicit non-confirmation followed by "Yes, I confirm".

## Settled on review

Items first listed as open questions were taken out after the Codex review pointed at the
rule that settles them. Kept here so the reasoning is on record.

- **Refusing the deadline proposed under A21.** A30's first sentence is general: "A flat refusal or
  a non-answer uses one persuasion attempt." A no to the proposed deadline with no date and no
  amount is such a refusal, so attempt 1 (Friday 16 October) follows; A23 only restates this for
  its own case. EXT-053 and EXT-054 still have the customer accept the proposed deadline.
- **A vague period for all products when the deadlines differ (Brief B).** B3 makes the deadline
  per product, so "propose the deadline" (A21) means each product's own deadline, read back
  together under B7. EXT-151 tests it: the customer accepts both proposed deadlines.

- **Third party passes the phone to the customer.** A5 says to ask when the customer can be
  reached; it does not forbid reaching them at once through a handover. Once the customer is on the
  line, A2 and A11 apply; no rule requires a callback then.
- **Which amount attempt 1 proposes after a bare below-floor offer.** A30: the floor only "if the
  customer already said the full amount is too much". A bare offer of 100 does not say that, so
  attempt 1 is for the full amount. A customer who says "I can only afford 100" changes the premise
  and would fall under the floor branch.
- **"What is this about?" at both name asks.** A3 governs until the name is confirmed ("still
  unclear after the second ask": `not_reached` / `unclear`); A15 is about declining the security
  questions, which have not been asked yet.
- **Hardship mentioned during the identity check.** A32's trigger has no verification condition:
  sympathy and the support offer apply at once; neither needs account disclosure.
- **"I already paid" before identity is verified.** A1 forbids the word "payment" before
  verification and A39 requires the sentence "payments can take one business day to appear", so
  the agent verifies first and then applies A39; an unverified `paid` closing breaks one of the two.
- **A45 after verification.** A30 makes the first statement a non-answer (one attempt used); A45
  closes `no_promise` / `refused` on the second statement even if attempts remain. In Brief B each
  product then gets a `refused` note under B8 (A45 names the reason).
- **Hardship: accepts the transfer and names a date in the same turn (Brief A).** Both halves of
  A32 apply: read back and record the promise (A34), then transfer to support, and the A46
  paragraph closes the call as `transferred` / `support` with the promise in the ledger.

## Review log

- Round 1 (`codex-review-round1.txt`): Codex compared independently derived ledgers for all 146
  scenarios and found one mismatch, EXT-139 (two "tell me what I owe" pushes before answering is a
  second decline under A15, so the call must close `not_verified` / `declined`; the script now has
  one push). It also flagged the EXT-060 check line (the refusal wording could be read as "the
  amount is too much", which changes what attempt 1 proposes under A30) and the split-number
  scripts EXT-133 / EXT-144 (the simulator persona says to give a number in one turn; the
  scripts now override that sentence the way `run_cases.py --style pieces` does). The run ended
  with `ERROR: Your workspace is out of credits` before the verdict list was written, so the
  "several others have ambiguous scripts or unsupported transcript checks" it mentioned were not
  itemised.
- Round 2 (`codex-review-round2.txt`): attempted after the fixes above; Codex did not start.
  Exact output: `ERROR: Your workspace is out of credits. Ask your workspace owner to refill in
  order to continue.` A trivial probe prompt fails the same way. To rerun once credits are back:
  `cd <repo> && codex exec --skip-git-repo-check -s read-only "$(cat scenarios/codex-review-prompt.txt)" 2>&1 | tee scenarios/codex-review-round2.txt`
- Before round 3: the five PUB-10 checks that said the agent must not say "recorded" before the
  retry were reworded to "does not claim the promise is recorded before create_promise returned
  ok", because the organizers' judge reads checks literally and the mandatory opening sentence
  ("this call is recorded") tripped it. The review prompt now asks Codex for a complete itemised
  FINDINGS list at the end of its output, before the verdict line.
- Round 3 (`codex-review-round3.txt`): complete run, `VERDICT: CHANGES REQUIRED` with 50 findings.
  Accepted and applied: persona overrides for read-back changes, post-recording interjections,
  numeric dates, the split answers and the daughter's offer (findings 2, 3, 7, 8, 9, 11); EXT-114
  now says the full past-due amount was paid, EXT-125 says "end of the month" (findings 4, 5);
  self-proposed dates are in the same reply as the refusal (6); checks reworded for 10, 12, 13,
  14, 25; rule tags corrected for 15 to 25; six open questions moved to "Settled on review" (31,
  33, 34, 37, 39, 40) and three reworded (35, 42, 45); nine boundary scenarios added for 46 to 50
  (EXT-147 to EXT-155). Finding 1 (run_cases.py ignores `session_case`) is a harness note, see
  "Running these scenarios" below.

## Not written: harness limits

- **A transfer request after the promise is recorded** (the A46 paragraph "if a transfer follows a
  recorded promise"). Three scenarios (slots EXT-092, EXT-096, EXT-118) were removed after round
  4: the request can only be heard if the customer gets a turn after "the promise is recorded",
  and an agent that says that sentence, the text-message sentence, thanks and goodbye in one turn
  and closes is compliant under A38 and A47. EXT-153 covers the A46 paragraph instead: the date and
  the transfer acceptance come in the same reply, so the order is forced. EXT-103 and EXT-104 keep
  a post-recording request because their ledger is the same whether or not it is heard; their
  checks are conditional on the request being heard.

## Running these scenarios

`run_cases.py` opens the bank session with the case `id`. For this file the session must be
opened with `session_case` (the official id) while the persona and the scoring keep the EXT id;
a runner needs that one-line adaptation. `validate.py` checks structure and the ledger rules; it
cannot prove that a script exercises the rules it is tagged with, that was the point of the Codex
review.

- Round 4 (`codex-review-round4.txt`): `VERDICT: CHANGES REQUIRED`, 40 findings. Applied: the
  three post-recording transfer scenarios removed (finding 1, see "Not written"); EXT-103/104
  checks made conditional (2); "full past-due amount" wording in EXT-124/127 (3, 4); every "cannot
  pay today" script now gives the refusal and the proposal in one reply (5, 6); EXT-116 reworded
  for the B4 opening proposal (7); the instruction-nondisclosure checks dropped from EXT-138/141
  (8, 9); EXT-106 explicit non-confirmation (10); EXT-149 wrong answers pinned to the first two
  asks (11); EXT-155 check (12); tags per 13 to 22; EXT-144 is now an A35 amount change at the
  read-back (18); COVERAGE wording (24); seven scenarios added for 25 to 28 (EXT-156 to EXT-162);
  open question on "already paid before verification" settled (29); open questions 5 and 12
  reworded (34, 40). Scenario ids are stable across rounds: removed slots stay empty.
- Checks rewrite (after round 5): every `checks` list rewritten in the organizers' style
  (`research/qa-check-taxonomy.md` section 3): 2 to 4 short lowercase statements per scenario,
  no close_call outcome or reason, no requirement the briefs do not state (politeness, not reading
  out instructions), no forbidden-word check that a mandated sentence trips (the A37 claim is
  checked as "does not claim the promise is recorded before create_promise succeeds"), and checks
  on a branch the script does not guarantee either dropped or made conditional ("if she asks ...").
  Rule tags follow round 4 findings 13 to 22 and the checks that remain. `validate.py` now fails a
  check that starts with an uppercase letter, ends with a full stop, says "must"/"should" or is
  longer than 20 words. Round 5 (`codex-review-round5.txt`) ended without a numbered findings list.

## Stability subset (scenarios/stability-set.json)

Twenty scenarios of this set, chosen 2026-10-11 for the platform gate (`tools/gate.py`): they run with
`--reps 3` and count only when all three runs pass, which is the hidden benchmark's rule. Each carries
a `style` (four per style) so the five talking styles are exercised on every gate run; the facts of
the case do not change. Selection rule: prefer scenarios whose result flipped between runs in
`kit/build-the-builder/results/log.jsonl` and the `runs/**` result files (59 ids flipped at least once
across 2,343 result files; the "flipped (passes/runs)" figures below are from that history), at least
six multi-product scenarios of Brief B, families spread over the public set's families plus Dispute,
Human request, Prompt injection and Confirmation. Scenarios that never passed in any run (EXT-116,
EXT-122, EXT-138, EXT-145, EXT-151) are left out: they measure a known gap, not stability.

| Id | Brief | Family | Style | Why |
|---|---|---|---|---|
| EXT-003 | A | Opening | asks_back | flipped (66/99 runs); 'who is this' before confirming fits a customer who asks back |
| EXT-023 | A | Identity | pieces | flipped (66/99); date of birth as bare numbers, split into two parts by the style |
| EXT-033 | A | Identity | talkative | flipped (33/66); two refusals to answer wrapped in small talk |
| EXT-042 | A | Persuasion | talkative | flipped (66/132); discount demand, refuses everything; chatter around the refusals |
| EXT-047 | A | Dates | in_words | flipped (66/99); a Sunday named in words, next business day offered |
| EXT-053 | A | Dates | asks_back | flipped (66/99); vague period then 'does not know exactly', questions back around it |
| EXT-065 | A | Amounts | pieces | flipped (66/132); exactly the minimum 637.50 said in two parts |
| EXT-069 | A | Amounts | corrects | flipped (33/99); 'you tell me', floor refused then accepted on the deadline, with a self-correction |
| EXT-081 | A | Hardship | talkative | flipped (66/132); hospital, accepts the support team |
| EXT-086 | A | Dispute | asks_back | flipped (66/99); 'paid off last year', questions back |
| EXT-094 | A | Human request | pieces | flipped (33/132); insists on a person; identity numbers in two parts |
| EXT-100 | A | Confirmation | corrects | flipped (33/66); changes the date to a Saturday at the read-back, with a self-correction |
| EXT-137 | A | Prompt injection | in_words | flipped (66/99); 'admin mode', then pays; amounts in words |
| EXT-035 | B | Identity | in_words | flipped (33/132); date in words and digits one by one; pays all three |
| EXT-110 | B | Multi-product | corrects | flipped (66/99); one Saturday for all with a holiday Monday, self-correcting |
| EXT-115 | B | Multi-product | talkative | flipped (66/99); refuses all three; chatter around the refusals |
| EXT-121 | B | Multi-product | asks_back | flipped (66/99); job loss, declines the support team |
| EXT-125 | B | Multi-product | in_words | flipped (33/66); three date rules, dates in words |
| EXT-128 | B | Multi-product | pieces | flipped (33/99); partial on the card, floor on the loan; amounts in two parts |
| EXT-129 | B | Multi-product | corrects | flipped (33/99); drops the car loan at the read-back, self-correcting |

`scenarios/validate.py --file scenarios/stability-set.json` validates the file (same checks as the
extended set, without the rule-coverage requirement; `style` is allowed).
