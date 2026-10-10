#!/usr/bin/env bash
# Stop the mock bank and its tunnel, if any.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for f in .tunnel.pid .pid; do
  if [ -f "$HERE/$f" ]; then
    pid="$(cat "$HERE/$f")"
    if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null && echo "stopped $f ($pid)"; fi
    rm -f "$HERE/$f"
  fi
done
rm -f "$HERE/.url"
