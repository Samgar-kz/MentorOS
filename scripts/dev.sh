#!/usr/bin/env bash
# One command to run MentorOS: backend (FastAPI) + frontend (Next.js).
# Bootstraps deps on first run, then starts both. Ctrl-C stops everything.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load local secrets (gitignored) if present — provides OPENAI_API_KEY for the tutor.
[ -f .env ] && { set -a; . ./.env; set +a; }

export MENTOROS_STORE="${MENTOROS_STORE:-data/default.events.jsonl}"

# Bootstrap so `make dev` is the only command you ever need to remember.
python3 -c "import fastapi, uvicorn" 2>/dev/null || { echo "→ installing API deps..."; python3 -m pip install -e ".[api]"; }
[ -d web/node_modules ] || { echo "→ installing web deps..."; ( cd web && npm install --no-audit --no-fund ); }

# Stop both child processes when this script exits (Ctrl-C included).
trap 'kill 0' EXIT

echo "MentorOS running → API http://localhost:8000   web http://localhost:3000   (Ctrl-C to stop)"
( PYTHONPATH=. python3 -m uvicorn mentoros.api:app --host 127.0.0.1 --port 8000 ) &
( cd web && npm run dev ) &
wait
