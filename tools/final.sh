#!/usr/bin/env bash
# The final-day one shot: the bank's zip (or an unpacked case folder) in, the phone agent and the submission draft out.
#
#   tools/final.sh <zip-or-folder> [--mock-url URL] [--dry-run]
#   tools/final.sh --submission            # only re-print submission.json with the current HEAD (after the commit)
#
# Steps, each echoed:  unzip into final/<name>/ (a zip) -> list the folder -> customers.json for the mock
# (mock/make_customers.py) -> the CONTRACT section the mock needs (python -m bank.adapters <contract>; edit
# mock/worker/src/index.js by hand, deploy, smoke) -> mock URL check (mock/.url or --mock-url; health) ->
# [--dry-run stops here] -> python3 builder/build.py <case> <mock_url> 2>&1 | tee traces/final.log ->
# submission/final.workflow.json -> git commit + submission.json draft.
# Idempotent and safe: nothing is deleted; an earlier traces/final.log is kept as traces/final.<time>.log.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python3; fi
fi

say() { printf '\n== %s\n' "$*"; }
die() { printf '\n!! %s\n' "$*" >&2; exit 1; }

print_submission() {
  local url="${1:-}" case="${2:-<case_folder>}"
  local commit; commit="$(git rev-parse HEAD 2>/dev/null || echo '?')"
  local dirty=""; [ -n "$(git status --porcelain 2>/dev/null)" ] && dirty=" (working tree not clean: commit the workflow and the trace, then re-run tools/final.sh --submission)"
  [ -z "$url" ] && [ -f mock/.url ] && url="$(tr -d '[:space:]' < mock/.url)"
  say "git commit: $commit$dirty"
  say "submission.json draft (send by e-mail before 20:00 UTC = 22:00 CEST)"
  COMMIT="$commit" URL="${url:-<from mock/.url>}" CASE="$case" "$PY" - <<'PYEOF'
import json, os, pathlib, subprocess
p = pathlib.Path("submission.json")
d = json.loads(p.read_text()) if p.exists() else {}
d.setdefault("team", "?")
d.setdefault("members", [{"name": "Yakup Keskin", "email": "yakupkeskin777@gmail.com"}])
try:
    d["repo"] = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True).strip() or d.get("repo", "?")
except Exception:
    d.setdefault("repo", "?")
d["commit"] = os.environ["COMMIT"]
d["run_command"] = "python3 builder/build.py %s %s 2>&1 | tee traces/final.log" % (os.environ["CASE"], os.environ["URL"])
d["workflow"] = "submission/final.workflow.json"
d["trace"] = "traces/final.log"
d["mock_url"] = os.environ["URL"]
print(json.dumps(d, indent=2, ensure_ascii=False))
if p.exists():
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    print("\n(written to submission.json; fields still '?' need a human)")
PYEOF
}

# ---- arguments
SRC=""; MOCK_URL=""; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mock-url) MOCK_URL="${2:-}"; shift 2 ;;
    --mock-url=*) MOCK_URL="${1#*=}"; shift ;;
    --dry-run) DRY=1; shift ;;
    --submission) print_submission; exit 0 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) [ -z "$SRC" ] || die "unexpected argument: $1"; SRC="$1"; shift ;;
  esac
done
[ -n "$SRC" ] || { sed -n '2,12p' "$0"; exit 2; }

# ---- 1. the case folder
if [ -f "$SRC" ] && [[ "$SRC" == *.zip ]]; then
  NAME="$(basename "$SRC" .zip)"
  CASE="final/$NAME"
  say "1. unzip $SRC into $CASE/ (existing files are kept, never overwritten)"
  mkdir -p "$CASE"
  unzip -n -q "$SRC" -d "$CASE"
  # a zip that holds one top-level folder (FreyaBank-Ekstre-Borc/...) : the case is that folder
  if [ ! -f "$CASE/BRIEF.md" ]; then
    inner="$(find "$CASE" -mindepth 1 -maxdepth 1 -type d ! -name '__MACOSX' | head -n 2)"
    if [ "$(printf '%s\n' "$inner" | grep -c .)" = 1 ] && [ -z "$(find "$CASE" -mindepth 1 -maxdepth 1 -type f ! -name '.DS_Store')" ]; then
      CASE="$inner"
    fi
  fi
elif [ -d "$SRC" ]; then
  CASE="${SRC%/}"
  say "1. case folder $CASE (already unpacked)"
else
  die "$SRC is neither a .zip nor a folder"
fi
[ -f "$CASE/BRIEF.md" ] || printf '   warning: no BRIEF.md in %s (the builder reads the folder anyway)\n' "$CASE"

say "2. the folder"
find "$CASE" -type f ! -name '.DS_Store' | sort | while read -r f; do printf '   %8s  %s\n' "$(wc -c < "$f" | tr -d ' ')" "$f"; done

# ---- 3. the test customers -> mock/worker/data/customers.json
say "3. test customers -> mock customers"
CUSTOMERS="$(find "$CASE" -type f \( -iname '*customer*.json' -o -iname '*musteri*.json' -o -iname '*müşteri*.json' -o -iname '*test*.json' \) | sort | head -n 1 || true)"
if [ -z "$CUSTOMERS" ]; then
  # any .json that is not an OpenAPI document
  CUSTOMERS="$(for f in $(find "$CASE" -type f -iname '*.json' | sort); do grep -lq '"openapi"' "$f" 2>/dev/null || echo "$f"; done | head -n 1 || true)"
fi
if [ -n "$CUSTOMERS" ]; then
  OUT=mock/worker/data/customers.json
  [ "$DRY" = 1 ] && OUT="final/.dry-run.customers.json" && mkdir -p final
  printf '   %s -> %s\n' "$CUSTOMERS" "$OUT"
  if "$PY" -I mock/make_customers.py "$CUSTOMERS" --out "$OUT"; then
    printf '   %s customers\n' "$("$PY" -I -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$OUT")"
  else
    printf '   make_customers failed: the file is shaped differently; adjust convert() in mock/make_customers.py and re-run\n'
  fi
  [ "$DRY" = 1 ] && printf '   (dry run: mock/worker/data/customers.json untouched)\n'
else
  printf '   no test-customers file found in %s; run mock/make_customers.py by hand\n' "$CASE"
fi

# ---- 4. the service contract -> CONTRACT section of the mock
say "4. service contract -> CONTRACT section (edit mock/worker/src/index.js by hand, then deploy + smoke)"
CONTRACT="$(for f in $(find "$CASE" -type f \( -iname '*.json' -o -iname '*.yaml' -o -iname '*.yml' \) | sort); do grep -lq -E '^\s*"?openapi"?\s*[:=]' "$f" 2>/dev/null && echo "$f"; done | head -n 1 || true)"
if [ -z "$CONTRACT" ]; then
  printf '   no OpenAPI document (.json/.yaml/.yml with an openapi key) found: the builder will stop with a trace error\n'
elif [[ "$CONTRACT" == *.json ]]; then
  printf '   %s\n\n' "$CONTRACT"
  "$PY" -m bank.adapters "$CONTRACT" | sed 's/^/   /' || printf '   bank.adapters could not read it; read the contract and fill CONTRACT by hand\n'
else
  printf '   %s is YAML: convert it first, e.g.\n   %s -c "import json,sys,yaml;json.dump(yaml.safe_load(open(sys.argv[1])),open(sys.argv[2],\"w\"),indent=1)" %s final/contract.json && %s -m bank.adapters final/contract.json\n' "$CONTRACT" "$PY" "$CONTRACT" "$PY"
fi

# ---- 5. the mock must be up
say "5. mock URL"
if [ -z "$MOCK_URL" ]; then
  if [ -f mock/.url ]; then
    MOCK_URL="$(tr -d '[:space:]' < mock/.url)"
    printf '   mock/.url: %s\n' "$MOCK_URL"
  else
    die "mock/.url is missing: deploy the mock first.
   cd mock/worker && npx -y wrangler@4 deploy        (needs CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID)
   echo https://freya-mock.<subdomain>.workers.dev > mock/.url
   mock/smoke.sh \"\$(cat mock/.url)\" <one customer id>
   then re-run: tools/final.sh $SRC"
  fi
else
  printf '   --mock-url: %s\n' "$MOCK_URL"
fi
MOCK_URL="${MOCK_URL%/}"
if curl -fsS --max-time 10 "$MOCK_URL/v1/health" >/tmp/final-health.$$ 2>&1; then
  printf '   health: %s\n' "$(head -c 300 /tmp/final-health.$$)"
else
  printf '   health check failed on %s/v1/health\n' "$MOCK_URL"
  [ "$DRY" = 1 ] || die "the mock does not answer; deploy it (cd mock/worker && npx -y wrangler@4 deploy; mock/smoke.sh $MOCK_URL) and re-run"
fi
rm -f /tmp/final-health.$$

if [ "$DRY" = 1 ]; then
  say "dry run: stopping before the builder. The real run would be:"
  printf '   %s builder/build.py %s %s 2>&1 | tee traces/final.log\n' "$PY" "$CASE" "$MOCK_URL"
  exit 0
fi

# ---- 6. the builder
mkdir -p traces submission
if [ -s traces/final.log ]; then
  KEEP="traces/final.$(date +%Y%m%d-%H%M%S).log"
  cp traces/final.log "$KEEP"
  printf '   earlier traces/final.log kept as %s\n' "$KEEP"
fi
say "6. builder: $PY builder/build.py $CASE $MOCK_URL 2>&1 | tee traces/final.log"
if ! "$PY" builder/build.py "$CASE" "$MOCK_URL" 2>&1 | tee traces/final.log; then
  die "the builder did not finish cleanly; read traces/final.log, then re-run the same command (the slot updates in place)"
fi

# ---- 7. the export -> submission/final.workflow.json
say "7. export -> submission/final.workflow.json"
EXPORT="$(grep -oE 'exported [^ ]+\.workflow\.json' traces/final.log | tail -n 1 | sed 's/^exported //' || true)"
if [ -n "$EXPORT" ] && [ -f "$EXPORT" ]; then
  if [ -s submission/final.workflow.json ] && ! cmp -s "$EXPORT" submission/final.workflow.json; then
    KEEP="submission/final.$(date +%Y%m%d-%H%M%S).workflow.json"
    cp submission/final.workflow.json "$KEEP"
    printf '   earlier submission/final.workflow.json kept as %s\n' "$KEEP"
  fi
  cp "$EXPORT" submission/final.workflow.json
  printf '   %s -> submission/final.workflow.json (%s nodes)\n' "$EXPORT" \
    "$("$PY" -I -c "import json,sys;print(len(json.load(open(sys.argv[1])).get('nodes',[])))" submission/final.workflow.json 2>/dev/null || echo '?')"
else
  printf '   no "exported ....workflow.json" line in traces/final.log: the build did not reach the export (floor or error); read the trace\n'
fi

# ---- 8. commit + submission.json
print_submission "$MOCK_URL" "$CASE"
say "next: git add submission/final.workflow.json traces/final.log $CASE && git commit -m 'Final: workflow and trace' && git push && tools/final.sh --submission"
