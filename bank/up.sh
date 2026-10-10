#!/usr/bin/env bash
# Start the mock bank on ${BANK_PORT:-8787}, bound to 0.0.0.0, pid in bank/.pid.
# With BANK_TUNNEL=1 and cloudflared installed, also start a quick tunnel; its public URL goes to bank/.url.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PORT="${BANK_PORT:-8787}"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
CASES="${BANK_CASES:-$ROOT/kit/build-the-builder/public-test-set.json}"

if [ -f "$HERE/.pid" ] && kill -0 "$(cat "$HERE/.pid")" 2>/dev/null; then
  echo "bank already running (pid $(cat "$HERE/.pid"))"; exit 0
fi

nohup "$PY" "$HERE/server.py" --host 0.0.0.0 --port "$PORT" --cases "$CASES" >"$HERE/.log" 2>&1 &
echo $! >"$HERE/.pid"
for _ in $(seq 1 50); do
  if curl -fsS "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1; then break; fi
  sleep 0.1
done
curl -fsS "http://127.0.0.1:$PORT/v1/health" >/dev/null || { echo "bank did not come up, see $HERE/.log"; exit 1; }
echo "bank up on http://0.0.0.0:$PORT/v1 (pid $(cat "$HERE/.pid"))"
echo "http://127.0.0.1:$PORT" >"$HERE/.url"

if [ "${BANK_TUNNEL:-0}" = "1" ] && command -v cloudflared >/dev/null 2>&1; then
  nohup cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate >"$HERE/.tunnel.log" 2>&1 &
  echo $! >"$HERE/.tunnel.pid"
  URL=""
  for _ in $(seq 1 120); do
    URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$HERE/.tunnel.log" | head -1 || true)"
    [ -n "$URL" ] && break
    sleep 0.5
  done
  if [ -z "$URL" ]; then echo "tunnel did not report a URL, see $HERE/.tunnel.log"; exit 1; fi
  echo "$URL" >"$HERE/.url"
  for _ in $(seq 1 30); do
    if curl -fsS "$URL/v1/health" >/dev/null 2>&1; then echo "tunnel up: $URL/v1/health ok"; exit 0; fi
    sleep 1
  done
  echo "tunnel URL $URL does not answer /v1/health yet"; exit 1
fi
