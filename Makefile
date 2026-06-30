# MentorOS — one command philosophy.
.PHONY: dev start seed test help

help:
	@echo "make dev    - run the whole app in DEV mode (API + web, hot reload)"
	@echo "make start  - run the whole app in PRODUCTION mode (API + built web)"
	@echo "make seed   - load the academic word list into the local store"
	@echo "make test   - run the test suite"
	@echo ""
	@echo "If clicking links downloads .html instead of opening, use 'make start' (prod)."

dev:
	@bash scripts/dev.sh

start:
	@bash scripts/start.sh

seed:
	@MENTOROS_STORE=data/default.events.jsonl PYTHONPATH=. python3 -m mentoros.cli seed

test:
	@PYTHONPATH=. python3 -m pytest -q
