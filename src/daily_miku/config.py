"""Validated configuration boundary for Daily Miku v2."""

from typing import Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    EmailStr,
    Field,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Safe configuration failure that never includes submitted values."""


class DatabaseSettings(BaseSettings):
    """Validate shared Selection Ledger connection configuration."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True
    )

    timezone_name: str = Field("Asia/Shanghai", alias="DAILY_MIKU_TIMEZONE")
    serverless: bool = Field(False, alias="VERCEL")
    database_url: SecretStr = Field(alias="DATABASE_URL")

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Require a known IANA timezone."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unknown IANA timezone") from exc
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        """Reject an empty database credential."""
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value

    @classmethod
    def from_environment(cls, **kwargs: Any) -> Self:
        """Load settings and reduce validation failures to safe field names."""
        try:
            return cls(**kwargs)
        except ValidationError as exc:
            fields = set()
            for error in exc.errors():
                field_name = str(error["loc"][0])
                field = cls.model_fields.get(field_name)
                fields.add(str(field.alias) if field and field.alias else field_name)
            raise ConfigurationError(
                f"Invalid configuration fields: {', '.join(sorted(fields))}"
            ) from None


class LedgerSettings(DatabaseSettings):
    """Validate configuration required by correction commands."""

    operator: str = Field(alias="DAILY_MIKU_OPERATOR")

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, value: str) -> str:
        """Reject an empty audit identity."""
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()


class InitializationSettings(DatabaseSettings):
    """Validate only dependencies used by legacy initialization."""

    tag: str = Field("daily-miku", alias="DAILY_MIKU_TAG")
    raindrop_token: SecretStr = Field(alias="RAINDROP_TOKEN")

    @field_validator("tag")
    @classmethod
    def validate_tag(cls, value: str) -> str:
        """Reject an empty Raindrop tag."""
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("raindrop_token")
    @classmethod
    def validate_raindrop_token(cls, value: SecretStr) -> SecretStr:
        """Reject an empty Raindrop credential."""
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value


class ImageSettings(DatabaseSettings):
    """Validate only dependencies required by image operator commands."""

    operator: str = Field(alias="DAILY_MIKU_OPERATOR")
    raindrop_token: SecretStr = Field(alias="RAINDROP_TOKEN")
    blob_read_write_token: SecretStr = Field(alias="BLOB_READ_WRITE_TOKEN")
    tag: str = Field("daily-miku", alias="DAILY_MIKU_TAG")

    @field_validator("operator", "tag")
    @classmethod
    def validate_image_operator(cls, value: str) -> str:
        """Require an audit identity for image mutations."""
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("raindrop_token", "blob_read_write_token")
    @classmethod
    def validate_image_secret(cls, value: SecretStr) -> SecretStr:
        """Reject empty image dependency credentials."""
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value


class Settings(LedgerSettings):
    """Own all v2 application environment parsing and validation."""

    tag: str = Field("daily-miku", alias="DAILY_MIKU_TAG")
    reconcile_secret: SecretStr = Field(alias="DAILY_MIKU_RECONCILE_SECRET")
    email_from: str = Field(alias="DAILY_MIKU_EMAIL_FROM")
    email_recipients_value: str = Field(alias="DAILY_MIKU_EMAIL_RECIPIENTS")
    raindrop_token: SecretStr = Field(alias="RAINDROP_TOKEN")
    blob_read_write_token: SecretStr = Field(alias="BLOB_READ_WRITE_TOKEN")
    smtp_host: str = Field(alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT", ge=1, le=65535)
    smtp_username: str = Field(alias="SMTP_USERNAME")
    smtp_password: SecretStr = Field(alias="SMTP_PASSWORD")

    @field_validator("tag", "smtp_host", "smtp_username")
    @classmethod
    def validate_nonempty(cls, value: str) -> str:
        """Reject empty operational identifiers."""
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator(
        "reconcile_secret",
        "raindrop_token",
        "blob_read_write_token",
        "smtp_password",
    )
    @classmethod
    def validate_nonempty_secret(cls, value: SecretStr) -> SecretStr:
        """Reject required credentials that are present but empty."""
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("email_recipients_value")
    @classmethod
    def validate_recipients(cls, value: str) -> str:
        """Validate comma-separated recipients before retaining their order."""
        entries = value.split(",")
        recipients: list[str] = []
        for entry in entries:
            address = str(entry).strip()
            if not cls._valid_email(address):
                raise ValueError("contains an invalid email address")
            if address not in recipients:
                recipients.append(address)
        if not recipients:
            raise ValueError("must contain at least one email address")
        return ",".join(recipients)

    @field_validator("email_from")
    @classmethod
    def validate_sender(cls, value: str) -> str:
        """Require one syntactically valid sender address."""
        if not cls._valid_email(value):
            raise ValueError("must be a valid email address")
        return value

    @staticmethod
    def _valid_email(value: str) -> bool:
        try:
            TypeAdapter(EmailStr).validate_python(value)
        except ValidationError:
            return False
        return True

    @property
    def email_recipients(self) -> tuple[str, ...]:
        """Return validated recipients in configured order."""
        return tuple(self.email_recipients_value.split(","))

    @classmethod
    def in_memory(cls) -> "Settings":
        """Create valid non-secret settings for isolated application tests."""
        return cls(
            DAILY_MIKU_OPERATOR="test-operator",
            DAILY_MIKU_RECONCILE_SECRET="not-a-real-secret",
            DAILY_MIKU_EMAIL_FROM="sender@example.com",
            DAILY_MIKU_EMAIL_RECIPIENTS="recipient@example.com",
            RAINDROP_TOKEN="not-a-real-token",
            DATABASE_URL="postgresql://unused",
            BLOB_READ_WRITE_TOKEN="not-a-real-token",
            SMTP_HOST="smtp.example.test",
            SMTP_USERNAME="test-user",
            SMTP_PASSWORD="not-a-real-password",
        )
