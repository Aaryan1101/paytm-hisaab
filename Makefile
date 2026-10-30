.PHONY: db dev test seed reset openapi probe

db:
	docker compose up -d db

dev: db
	uv run uvicorn app.main:app --reload --port 8000

test:
	uv run pytest -q

openapi:
	uv run python -m scripts.export_openapi

reset:
	curl -s -X POST localhost:8000/demo/reset

probe:
	uv run python -m scripts.probe_sarvam chat
