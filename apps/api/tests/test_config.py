"""Tests for participant-data path configuration."""

from pathlib import Path

from app.config import DEFAULT_DATA_DIR, resolve_data_dir


def test_default_data_dir_uses_ignored_participant_bundle(monkeypatch) -> None:
    monkeypatch.delenv("SDOC_DATA_DIR", raising=False)

    assert resolve_data_dir() == DEFAULT_DATA_DIR


def test_data_dir_can_be_overridden_by_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SDOC_DATA_DIR", str(tmp_path))

    assert resolve_data_dir() == tmp_path


def test_explicit_data_dir_takes_precedence(monkeypatch, tmp_path: Path) -> None:
    environment_path = tmp_path / "environment"
    explicit_path = tmp_path / "explicit"
    monkeypatch.setenv("SDOC_DATA_DIR", str(environment_path))

    assert resolve_data_dir(explicit_path) == explicit_path
