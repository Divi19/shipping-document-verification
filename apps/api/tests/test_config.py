"""Tests for participant-data path configuration."""

from pathlib import Path

import pytest

from app.config import DEFAULT_DATA_DIR, case_store_path, resolve_data_dir


def test_default_data_dir_uses_ignored_participant_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SDOC_DATA_DIR", raising=False)

    assert resolve_data_dir() == DEFAULT_DATA_DIR


def test_data_dir_can_be_overridden_by_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SDOC_DATA_DIR", str(tmp_path))

    assert resolve_data_dir() == tmp_path


def test_explicit_data_dir_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environment_path = tmp_path / "environment"
    explicit_path = tmp_path / "explicit"
    monkeypatch.setenv("SDOC_DATA_DIR", str(environment_path))

    assert resolve_data_dir(explicit_path) == explicit_path


def test_case_store_path_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SDOC_CASE_STORE_PATH", raising=False)

    assert case_store_path() is None


def test_case_store_path_can_be_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    configured = tmp_path / "cases.json"
    monkeypatch.setenv("SDOC_CASE_STORE_PATH", str(configured))

    assert case_store_path() == configured
