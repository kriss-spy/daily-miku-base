"""Tests for transactional numbered v2 database migrations."""

from copy import deepcopy
from importlib.resources import files
import re
from types import TracebackType

import pytest

from daily_miku.ledger.migrations import MigrationRunner

pytestmark = pytest.mark.unit


class FakeResult:
    """Rows returned by the migration database fake."""

    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class MigrationDatabase:
    """Transactional schema fake used through the runner's public API."""

    def __init__(self) -> None:
        self.tables: set[str] = set()
        self.versions: dict[int, str] = {}
        self.fail_migration = False

    def connect(self) -> "MigrationConnection":
        return MigrationConnection(self)


class MigrationConnection:
    """Connection that commits or restores all schema changes on exit."""

    def __init__(self, database: MigrationDatabase) -> None:
        self.database = database
        self.snapshot: tuple[set[str], dict[int, str]] | None = None

    def __enter__(self) -> "MigrationConnection":
        self.snapshot = deepcopy((self.database.tables, self.database.versions))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            assert self.snapshot is not None
            self.database.tables, self.database.versions = self.snapshot

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        normalized = query.strip()
        if normalized.startswith("LOCK TABLE"):
            return FakeResult()
        if normalized.startswith("SELECT version, name"):
            return FakeResult(
                [(version, name) for version, name in self.database.versions.items()]
            )
        if normalized.startswith("SELECT version FROM schema_migrations"):
            versions = sorted(self.database.versions, reverse=True)
            return FakeResult([(versions[0],)] if versions else [])
        if normalized.startswith("INSERT INTO schema_migrations"):
            version, name = params
            assert isinstance(version, int)
            assert isinstance(name, str)
            self.database.versions[version] = name
            return FakeResult()

        self.database.tables.update(
            re.findall(r"CREATE TABLE(?: IF NOT EXISTS)? ([a-z_]+)", query)
        )
        if self.database.fail_migration and "selection_ledger" in query:
            raise RuntimeError("injected migration failure")
        return FakeResult()


class TestMigrationRunner:
    """Transactional migration behavior for an empty database."""

    def test_applies_once_and_exposes_schema_version(self) -> None:
        database = MigrationDatabase()
        runner = MigrationRunner(database.connect)

        first = runner.apply()
        second = runner.apply()

        assert first.applied_versions == (1, 2, 3)
        assert second.applied_versions == ()
        assert second.current_version == runner.expected_version == 3
        assert database.tables == {
            "schema_migrations",
            "selection_ledger",
            "selection_corrections",
            "reconciliation_runs",
            "image_provenance",
            "active_images",
            "image_withdrawals",
        }
        assert runner.current_version() == 3

    def test_failure_rolls_back_the_complete_apply(self) -> None:
        database = MigrationDatabase()
        database.fail_migration = True
        runner = MigrationRunner(database.connect)

        with pytest.raises(RuntimeError, match="injected migration failure"):
            runner.apply()

        assert database.tables == set()
        assert database.versions == {}


def test_reconciliation_state_migration_constrains_terminal_shapes() -> None:
    sql = (
        files("daily_miku.ledger.migrations")
        .joinpath("0002_reconciliation_run_state.sql")
        .read_text(encoding="utf-8")
    )

    assert "reconciliation_runs_terminal_state_check" in sql
    assert "status = 'running'" in sql
    assert "status = 'complete'" in sql
    assert "status IN ('incomplete', 'failed')" in sql
    assert "error_code IS NOT NULL" in sql


def test_image_migration_separates_retry_identity_from_content_digest() -> None:
    """Keep command retries idempotent while retaining append-only provenance."""
    sql = (
        files("daily_miku.ledger.migrations")
        .joinpath("0003_controlled_images.sql")
        .read_text(encoding="utf-8")
    )

    assert "ingest_id UUID NOT NULL UNIQUE" in sql
    assert "CREATE INDEX image_provenance_identity_digest_idx" in sql
    assert "CREATE UNIQUE INDEX image_provenance_identity_digest_idx" not in sql
