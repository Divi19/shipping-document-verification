"""Runtime configuration for the API and pipeline."""

import os
from pathlib import Path

# Root of the extracted participant bundle (inbox/ + attachments/).
# Overridable so the same code runs locally, in tests, and in the deployed service.
DATA_DIR_ENV = "SDOC_DATA_DIR"

# app/config.py -> app -> api -> apps -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]

# Datasets live in the gitignored local-data/ directory at the repository root,
# so paths stay stable no matter which directory a script is run from.
LOCAL_DATA = REPO_ROOT / "local-data"
DEFAULT_DATA_DIR = LOCAL_DATA / "sdoc-hackathon-bundle"


def data_dir() -> Path:
    """Return the configured dataset root as an absolute path."""
    configured = os.environ.get(DATA_DIR_ENV)
    return Path(configured).resolve() if configured else DEFAULT_DATA_DIR


def inbox_dir() -> Path:
    """Return the directory holding the email JSON records."""
    return data_dir() / "inbox"


def resolve_within(root: Path, *parts: str) -> Path:
    """Join ``parts`` onto ``root`` and refuse to escape it.

    Path parameters reach us straight from HTTP, so every filesystem access is
    confined to the dataset directory instead of trusting the caller.
    """
    candidate = root.joinpath(*parts).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Path escapes the dataset directory: {candidate}")
    return candidate
