#!/usr/bin/env bash
# Fan-out translation across many languages, P at a time.
#
#   ./fanout.sh <P> <lang> [lang ...]        e.g.  ./fanout.sh 4 ta ml bn gu kn ...
#
# Each language runs translate_run.py over weeks 1-28 independently. translate_run is idempotent
# (skips a scene/lang whose target already exists and is aligned), resumable, writes a per-language
# trace (trace.<lang>.jsonl), and aborts its own track if the backend goes down (3 fails in a row) —
# so this is safe to re-run and safe to run many languages at once. Each track logs to
# logs/fanout_<lang>.log so the parallel output does not interleave.
#
# P is bounded by the Gemini quota, NOT cores — start small (3-4), watch the logs for 429s, ramp up.
set -u
cd "$(dirname "$0")"
set -a; . ./.env 2>/dev/null; set +a
export GOOGLE_CLOUD_LOCATION=global
mkdir -p logs

P="$1"; shift
echo "fanout: P=$P over [$*]"
printf '%s\n' "$@" | xargs -P "$P" -I{} bash -c '
  echo "[start $1]"
  .venv/bin/python translate_run.py --weeks 1-28 --langs "$1" > "logs/fanout_$1.log" 2>&1
  echo "[done $1 rc=$?]"
' _ {}
echo "===== FANOUT COMPLETE ====="
