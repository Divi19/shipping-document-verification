"""Runtime configuration for the API and pipeline."""

import os
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = REPOSITORY_ROOT
LOCAL_DATA = REPOSITORY_ROOT / "local-data"
DEFAULT_DATA_DIR = REPOSITORY_ROOT / "local-data" / "sdoc-hackathon-bundle"
DATA_DIR_ENV = "SDOC_DATA_DIR"
CASE_STORE_PATH_ENV = "SDOC_CASE_STORE_PATH"


def resolve_data_dir(override: str | Path | None = None) -> Path:
    """Resolve the participant-data root from an override, environment, or default."""
    configured = override or os.getenv(DATA_DIR_ENV)
    return Path(configured).expanduser().resolve() if configured else DEFAULT_DATA_DIR


def data_dir() -> Path:
    """Return the configured dataset root as an absolute path."""
    return resolve_data_dir()


def case_store_path() -> Path | None:
    """Return the optional file used to persist review state between restarts."""
    configured = os.getenv(CASE_STORE_PATH_ENV)
    return Path(configured).expanduser().resolve() if configured else None


def inbox_dir() -> Path:
    """Return the directory holding the email JSON records."""
    return data_dir() / "inbox"


def resolve_within(root: Path, *parts: str) -> Path:
    """Join ``parts`` onto ``root`` and refuse to escape it.

    Path parameters reach us straight from HTTP, so every filesystem access is
    confined to the dataset directory instead of trusting the caller.
    """
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"Path escapes the dataset directory: {candidate}")
    return candidate
