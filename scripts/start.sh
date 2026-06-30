#!/usr/bin/env bash
# Production mode: API + a BUILT web frontend (next build && next start).
# Use this to actually *use* the app. It avoids a dev-mode quirk where some browsers
# download pages (plan.html, assessment.html) on link clicks instead of navigating —
# that only happens with `next dev` (RSC streaming); a production build navigates normally.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load local secrets (gitignored) if present — provides OPENAI_API_KEY for the tutor.
[ -f .env ] && { set -a; . ./.env; set +a; }

export MENTOROS_STORE="${MENTOROS_STORE:-data/default.events.jsonl}"

python3 -c "import fastapi, uvicorn" 2>/dev/null || { echo "→ installing API deps..."; python3 -m pip install -e ".[api]"; }
[ -d web/node_modules ] || { echo "→ installing web deps..."; ( cd web && npm install --no-audit --no-fund ); }

echo "→ building web (production)…"
( cd web && npm run build )

trap 'kill 0' EXIT
echo "MentorOS (prod) → API http://localhost:8000   web http://localhost:3000   (Ctrl-C to stop)"
( PYTHONPATH=. python3 -m uvicorn mentoros.api:app --host 127.0.0.1 --port 8000 ) &
( cd web && npm run start ) &
wait
