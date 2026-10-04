.PHONY: install lint format test check build demo clean

PY ?= uv run

install:
	uv venv
	uv pip install -e ".[dev]"

lint:
	$(PY) ruff check .
	$(PY) ruff format --check .

format:
	$(PY) ruff format .
	$(PY) ruff check --fix .

test:
	$(PY) pytest -q

check: lint test

build:
	rm -rf dist
	uv build

demo:
	$(PY) mcp-egress run --calls examples/calls.json --out /tmp/mcp-egress-demo.json -- python tests/fixtures/proxied_server.py

clean:
	rm -rf dist build .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
