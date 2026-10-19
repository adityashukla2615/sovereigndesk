# Thin wrapper: every task lives in tasks.py so Windows (no make) and CI run the same code.
# Pass extra flags with ARGS, e.g. `make dev ARGS=--offline`.
PY ?= python3
TASKS := setup dev test lint fmt api build check seed check-secrets clean

.PHONY: $(TASKS) up down logs help

$(TASKS):
	$(PY) tasks.py $@ $(ARGS)

up:
	docker compose up --build --detach --wait

down:
	docker compose down

logs:
	docker compose logs --follow

help:
	$(PY) tasks.py --help
