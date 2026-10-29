.PHONY: install dev test lint typecheck demo web-local

install:
	uv sync --group dev

dev:
	uv run uvicorn app.main:app --reload --port 8000

test:
	uv run pytest -q

lint:
	uv run ruff check . && uv run ruff format --check .

typecheck:
	uv run mypy app/

demo:
	uv run python scripts/demo_borrador.py

web-local:
	./scripts/web_local.sh
