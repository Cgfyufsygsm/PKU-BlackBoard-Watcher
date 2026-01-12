#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

mkdir -p logs

# Avoid overlapping runs (cron may overlap if a run takes too long).
mkdir -p data
if command -v flock >/dev/null 2>&1; then
  exec 200>"$ROOT/data/cron.lock"
  flock -n 200 || exit 0
fi

LIMIT="${PUSH_LIMIT_PER_RUN:-100}"

run_python() {
  # Prefer conda run for cron (non-interactive; does not rely on conda activate).
  local env_name="${CONDA_ENV_NAME:-bbwatcher}"
  if command -v conda >/dev/null 2>&1; then
    conda run -n "$env_name" python -m app.main --run --limit "$LIMIT"
    return
  fi
  if [[ -x "$HOME/miniconda3/bin/conda" ]]; then
    "$HOME/miniconda3/bin/conda" run -n "$env_name" python -m app.main --run --limit "$LIMIT"
    return
  fi
  python -m app.main --run --limit "$LIMIT"
}

{
  echo "===== $(date -Is) cron run start ====="
  run_python
  echo "===== $(date -Is) cron run end ====="
} >>logs/run.log 2>&1
