"""Tests for the v2 configuration boundary."""

import pytest
from pydantic import ValidationError

from daily_miku.config import ConfigurationError, LedgerSettings, Settings

pytestmark = pytest.mark.unit


def test_ledger_settings_require_only_correction_configuration() -> None:
    settings = LedgerSettings.from_environment(
        DAILY_MIKU_OPERATOR="operator",
        DATABASE_URL="postgresql://ledger",
        _env_file=None,
    )

    assert settings.operator == "operator"
    assert settings.database_url.get_secret_value() == "postgresql://ledger"


def test_settings_apply_defaults_and_parse_recipients() -> None:
    values = Settings.in_memory().model_dump()
    values["email_recipients_value"] = (
        " first@example.com,second@example.com,first@example.com "
    )
    settings = Settings(**values)

    assert settings.timezone_name == "Asia/Shanghai"
    assert settings.tag == "daily-miku"
    assert settings.serverless is False
    assert settings.smtp_port == 587
    assert settings.email_recipients == (
        "first@example.com",
        "second@example.com",
    )


def test_environment_loads_comma_separated_recipients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings.in_memory()
    for field_name, field in Settings.model_fields.items():
        alias = str(field.alias)
        value = settings.model_dump()[field_name]
        if hasattr(value, "get_secret_value"):
            value = value.get_secret_value()
        monkeypatch.setenv(alias, str(value))
    monkeypatch.setenv(
        "DAILY_MIKU_EMAIL_RECIPIENTS", "first@example.com, second@example.com"
    )

    loaded = Settings.from_environment(_env_file=None)

    assert loaded.email_recipients == (
        "first@example.com",
        "second@example.com",
    )


def test_empty_required_secret_is_rejected() -> None:
    values = Settings.in_memory().model_dump()
    values["RAINDROP_TOKEN"] = ""

    with pytest.raises(ValidationError, match="must not be empty"):
        Settings(**values)


def test_environment_failure_names_fields_without_exposing_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "credential-that-must-not-leak"
    monkeypatch.setenv("RAINDROP_TOKEN", secret)

    with pytest.raises(ConfigurationError) as caught:
        Settings.from_environment(_env_file=None)

    message = str(caught.value)
    assert "DAILY_MIKU_OPERATOR" in message
    assert secret not in message


def test_invalid_timezone_fails_safely() -> None:
    values = Settings.in_memory().model_dump()
    values["timezone_name"] = "Not/A_Timezone"

    with pytest.raises(ConfigurationError, match="DAILY_MIKU_TIMEZONE"):
        Settings.from_environment(**values)
