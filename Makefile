# MentorOS — one command philosophy: you only need `make dev`.
.PHONY: dev seed test help

help:
	@echo "make dev   - run the whole app (API + web); bootstraps deps on first run"
	@echo "make seed  - load the academic word list into the local store"
	@echo "make test  - run the test suite"

dev:
	@bash scripts/dev.sh

seed:
	@MENTOROS_STORE=data/default.events.jsonl PYTHONPATH=. python3 -m mentoros.cli seed

test:
	@PYTHONPATH=. python3 -m pytest -q
