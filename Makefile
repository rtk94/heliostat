PYTHON ?= python3.13
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: venv test lint fmt conformance clean

venv:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev]"

test:
	$(BIN)/pytest

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

fmt:
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

conformance:
	@echo "not yet implemented (Phase 1a)"

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache
