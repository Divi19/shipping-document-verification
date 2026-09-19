import json
from pathlib import Path

from app.main import app

OUTPUT_PATH = Path(__file__).parents[1] / "openapi.json"


def main() -> None:
    OUTPUT_PATH.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
