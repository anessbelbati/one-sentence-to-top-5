#!/bin/bash
# The pilot's API models, from this machine (network calls only; nothing heavy runs locally). Cached lists are skipped,
# so a rerun after a failure only redoes what failed.
#   bash inject/run_api.sh            # all of them
#   bash inject/run_api.sh jev        # only the Jev modes (or: openrouter, zerank)
# Jev goes through OpenRouter's System One endpoint, pinned to typesafe/jev-1.13 (the version that answered the
# benchmark, jev-1.13.0), on the OpenRouter key; JEV_DIRECT=1 uses TypeSafe's own API and JEV_API_KEY instead.
# FLOOR (USD, default 3): a model starts only if the OpenRouter account's remaining credit minus what that model is
# expected to cost stays at or above FLOOR, so a run never drains an account that other apps share. Expected costs are
# one search list's measured cost (2026-09-24) times the 600 lists, plus about 10%.
set -e
cd "$(dirname "$0")/.."
want=${1:-all}
FLOOR=${FLOOR:-3}
stopped=""
guard() {
  uv run python - "$FLOOR" "${1:-0}" << 'EOF'
import os, sys, requests
from dotenv import load_dotenv
load_dotenv(".env")
floor, need = float(sys.argv[1]), float(sys.argv[2])
h = {"Authorization": "Bearer " + os.environ.get("OPENROUTER_API_KEY", "")}
r = requests.get("https://openrouter.ai/api/v1/credits", headers=h, timeout=30)
if r.status_code != 200:
    sys.exit(f"OpenRouter key in .env is not usable (HTTP {r.status_code}: {r.text[:120]}). Put a working key in .env as OPENROUTER_API_KEY=...")
d = r.json()["data"]
left = d["total_credits"] - d["total_usage"]
print(f"OpenRouter account credit left: ${left:.2f}; next model about ${need:.2f}; stop line ${floor:.2f}")
if left - need < floor:
    sys.exit(f"STOPPED: running it would take the account below ${floor:.2f}")
EOF
}
run() {   # model, candidate set, workers, expected cost in USD
  if [ -n "$stopped" ]; then echo "skipped $1 (stopped earlier)"; return 0; fi
  if ! guard "$4"; then stopped=1; echo "skipped $1"; return 0; fi
  uv run python run.py --model "$1" --dataset "$2" --variant inject --workers "$3"
}
if [ "$want" = all ] || [ "$want" = zerank ]; then uv run python run.py --model zerank-2 --dataset inj-list --variant inject --workers 12; fi
if [ "$want" = all ] || [ "$want" = jev ]; then
  if [ -z "$JEV_DIRECT" ]; then export JEV_URL=https://openrouter.ai/api/v1/systemone JEV_MODEL=typesafe/jev-1.13; fi
  run jev-score-batch inj-list 8 0.45; run jev-choice inj-list 8 0.36; run jev-noul-pair inj-pair 16 0.15
  unset JEV_URL JEV_MODEL
fi
if [ "$want" = all ] || [ "$want" = openrouter ]; then
  run deepseek-json inj-list 8 2.30; run cohere-pro inj-list 4 1.65; run cohere-fast inj-list 4 1.32
fi
guard 0 || true
uv run python inject/analyze.py > results/inject/pilot_table.txt && head -16 results/inject/pilot_table.txt
uv run python inject/writeup.py
