from pathlib import Path

import pytest

from analytics.settings import Settings


def test_defaults_use_the_documented_port() -> None:
    assert Settings(_env_file=None).port == 5600  # type: ignore[call-arg]


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANALYTICS_PORT", "5999")
    assert Settings(_env_file=None).port == 5999  # type: ignore[call-arg]


def test_env_example_lists_every_setting() -> None:
    text = Path(".env.example").read_text()
    for name in Settings.model_fields:
        assert f"ANALYTICS_{name.upper()}=" in text, name
