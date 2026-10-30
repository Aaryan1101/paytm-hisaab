"""Writes shared/openapi.json: the contract the Android and web clients generate their code from.

Usage: uv run python -m scripts.export_openapi
"""
import json
from pathlib import Path

from app.main import create_app

OUT = Path("shared/openapi.json")


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(create_app().openapi(), indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
