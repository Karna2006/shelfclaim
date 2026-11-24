.PHONY: dev test lint fmt check replay eval reprice markers modal-deploy

dev:
	uv run uvicorn app.server.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

check: lint test

replay:
	uv run python -m app.cli replay $(SWEEP)

eval:
	uv run python -m app.cli evaluate --sweep $(SWEEP) --gt eval/ground_truth --out docs/results.md

reprice:
	uv run python -m app.cli reprice --sweep $(SWEEP) --country GB --limit 10

markers:
	uv run python -m app.cli make-markers --ids 0 1 2 --size-mm 100 --out markers.pdf

modal-deploy:
	uv run --extra gpu modal deploy gpu/modal_recon.py
