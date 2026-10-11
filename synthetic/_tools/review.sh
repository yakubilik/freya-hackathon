#!/bin/zsh
# usage: review.sh <letter> <round>   -- codex review of one synthetic brief, run from a temp dir, output to synthetic/<letter>/review-round<N>.md
set -u
L=$1; R=$2
SYN="$(cd "$(dirname "$0")/.." && pwd)"
KIT="$(cd "$SYN/../kit/build-the-builder" && pwd)"
TMP=$(mktemp -d /tmp/synrev-$L-XXXX)
P=$TMP/prompt.txt
{
cat <<'HDR'
You are reviewing synthetic test material for a voice-agent builder. The material imitates a bank's collections-call brief plus its tool API file and practice cases. Review it as a strict, adversarial auditor. Do not rewrite the files; report findings.

Check, and report each finding with a severity (BLOCKER / MAJOR / MINOR), the file, the exact place, what is wrong and the smallest fix:

1. Internal consistency of the brief: every rule is applicable; no two rules contradict, unless the material is raw (mail, policy, memo, codes) and the memo or the mail explicitly resolves the contradiction with a stated precedence. The brief must state its own calendar (holidays and business-day definition).
2. Every case in cases.json: recompute by hand, from the brief's own deadline rule and calendar, the deadline of each product, the floor, and what the script leads to. Confirm or refute the expected outcome, reason, promise amount(s), promise date(s), notes, callbacks and transfers. Show your date arithmetic for each promise and callback. Pay attention to weekends, the holidays listed in the brief, "next <weekday>" definitions, calendar-day vs business-day rules, and roll-forward vs roll-back rules.
3. api.json is valid OpenAPI 3 (structure, request bodies, response schemas), and it contains EXACTLY these seven tool paths and no others: verify_identity, get_account, create_promise, schedule_callback, transfer_to_agent, add_note, close_call. The brief must refer to tools only by these names, and must use only field names and allowed values (enums) that exist in api.json. The cases must use only product types, note reasons, queues and close outcomes/reasons that exist in api.json or in the brief's own tables.
4. Every "checks" entry of every case is judgeable from a call transcript (plus the tool calls shown in it) by a judge model: no check should depend on hidden state or on something the transcript cannot show.
5. Nothing is copied from the two public briefs (given below for comparison): structure and vocabulary may be similar, but no sentence may be a copy, and the rules and values must differ.
6. The cases' customers have 1 to 3 products; `now` varies across the cases (different days and times); a "style" field (one of pieces, corrects, talkative, asks_back, in_words) appears on at least two cases; at least one case has a correct non-promise outcome (dispute, callback, not verified, hardship, refusal).
7. For raw material: the memo must change at least two rules of the policy, and the cases must be computed under the memo, not the policy. Flag any case whose expected value would be the same under the old and the new rule when a discriminating case was clearly intended.

Output format, strictly:
## FINDINGS
A numbered list; each item: severity, file, place, problem, fix. Write "none" if there are none.
## DATE ARITHMETIC
One line per promise/callback: case id, product, your derivation, agrees/disagrees with expected.
## VERDICT
One line: VERDICT: PASS (no BLOCKER or MAJOR) or VERDICT: FIX (at least one BLOCKER or MAJOR).

================ PUBLIC BRIEF A (for the copy check only) ================
HDR
cat $KIT/briefs/brief-a.md
echo; echo "================ PUBLIC BRIEF B (for the copy check only) ================"
cat $KIT/briefs/brief-b.md
echo; echo "================ MATERIAL UNDER REVIEW: brief $L ================"
for f in brief.md mail.md policy.md memo.md codes.md api.json cases.json README.md; do
  if [ -f $SYN/$L/$f ]; then echo; echo "---------------- FILE: $L/$f ----------------"; cat $SYN/$L/$f; fi
done
} > $P
cd $TMP
codex exec --skip-git-repo-check -s read-only -m gpt-6-astra -c model_reasoning_effort=high "$(cat $P)" < /dev/null > $SYN/$L/review-round$R.md 2> $TMP/stderr.log
echo "exit $? for $L round $R; stderr lines $(wc -l < $TMP/stderr.log)"
