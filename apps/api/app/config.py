"""Application path configuration."""

import os
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = REPOSITORY_ROOT / "local-data" / "sdoc-hackathon-bundle"


def resolve_data_dir(override: str | Path | None = None) -> Path:
    """Resolve the participant-data root from an override, environment, or default."""
    configured = override or os.getenv("SDOC_DATA_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_DATA_DIR
