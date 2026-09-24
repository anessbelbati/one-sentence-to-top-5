#!/bin/bash
# The follow-up's API models, from this machine (network calls only). Cached rows are skipped, so a rerun only redoes
# what failed or what the money floor stopped.
#   bash inject/run_followup_api.sh
# Cohere and zerank-2 score each passage on its own, so one call per search covers all six follow-up kinds (inj-batch,
# with the clean target as a control). The models that read the whole list (Jev rubric and one pick, DeepSeek) get a
# full list per kind; the per-page Jev yes/no gets the edited page alone (inj-pair).
# FLOOR (USD, default 3): each step starts only if the OpenRouter account's remaining credit minus the step's expected
# cost stays at or above FLOOR. Steps run most important first; expected costs are the pilot's measured per-list costs.
set -e
cd "$(dirname "$0")/.."
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
    sys.exit(f"OpenRouter key in .env is not usable (HTTP {r.status_code}: {r.text[:120]})")
d = r.json()["data"]
left = d["total_credits"] - d["total_usage"]
print(f"OpenRouter account credit left: ${left:.2f}; next step about ${need:.2f}; stop line ${floor:.2f}")
if left - need < floor:
    sys.exit(f"STOPPED: running it would take the account below ${floor:.2f}")
EOF
}
step() {   # model, candidate set, kind, workers, expected cost in USD
  if [ -n "$stopped" ]; then echo "skipped $1 $3 (stopped earlier)"; return 0; fi
  if ! guard "$5"; then stopped=1; echo "skipped $1 $3"; return 0; fi
  uv run python run.py --model "$1" --dataset "$2" --variant "$3" --workers "$4" | tail -1
}
# zerank-2 bills the ZeroEntropy account, not OpenRouter: no guard.
uv run python run.py --model zerank-2 --dataset inj-batch --variant batch --workers 12 | tail -1
step cohere-pro inj-batch batch 4 0.28
step cohere-fast inj-batch batch 4 0.22
export JEV_URL=https://openrouter.ai/api/v1/systemone JEV_MODEL=typesafe/jev-1.13
for v in para offecho offstuff related offtopic offpara; do step jev-score-batch inj-list $v 8 0.05; done
step jev-noul-pair inj-pair followup 16 0.03
for v in para offecho offstuff related offtopic offpara; do step jev-choice inj-list $v 8 0.04; done
unset JEV_URL JEV_MODEL
step cohere-pro inj-list para 4 0.28        # check: the full list for one kind, against the one-call-per-search route
for v in para offecho offstuff related offtopic offpara; do step deepseek-json inj-list $v 8 0.25; done
guard 0 || true
