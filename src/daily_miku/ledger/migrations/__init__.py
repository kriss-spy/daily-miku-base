"""Transactional numbered migration runner."""

from dataclasses import dataclass
from importlib.resources import files

from ..database import ConnectionFactory, postgres_connections


@dataclass(frozen=True)
class Migration:
    """One ordered immutable schema migration."""

    version: int
    name: str
    sql: str


@dataclass(frozen=True)
class MigrationReport:
    """Observable result of a migration apply."""

    applied_versions: tuple[int, ...]
    current_version: int


def _load_migrations() -> tuple[Migration, ...]:
    directory = files(__package__)
    migrations = []
    for resource in sorted(directory.iterdir(), key=lambda item: item.name):
        if resource.name.endswith(".sql"):
            version_text, name = resource.name.removesuffix(".sql").split("_", 1)
            migrations.append(
                Migration(int(version_text), name, resource.read_text(encoding="utf-8"))
            )
    return tuple(migrations)


def expected_schema_version() -> int:
    """Return the schema version required by this release artifact."""
    migrations = _load_migrations()
    return migrations[-1].version if migrations else 0


class MigrationRunner:
    """Apply the complete known migration set in one transaction."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory
        self._migrations = _load_migrations()
        if not self._migrations:
            raise RuntimeError("No database migrations are packaged")

    @classmethod
    def from_url(
        cls, database_url: str, *, local_pool: bool = False
    ) -> "MigrationRunner":
        """Build migration tooling for a pooled Postgres URL."""
        return cls(postgres_connections(database_url, local_pool=local_pool))

    @property
    def expected_version(self) -> int:
        """Return the schema version required by this application."""
        return self._migrations[-1].version

    def apply(self) -> MigrationReport:
        """Atomically apply every migration not already recorded."""
        with self._connection_factory() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, "
                "name TEXT NOT NULL, "
                "applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            connection.execute("LOCK TABLE schema_migrations IN EXCLUSIVE MODE")
            rows = connection.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = {int(row[0]): str(row[1]) for row in rows}
            self._validate_history(applied)

            newly_applied = []
            for migration in self._migrations:
                if migration.version in applied:
                    continue
                connection.execute(migration.sql)
                connection.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                    (migration.version, migration.name),
                )
                newly_applied.append(migration.version)

        return MigrationReport(tuple(newly_applied), self.expected_version)

    def current_version(self) -> int:
        """Read the latest applied version from an initialized database."""
        with self._connection_factory() as connection:
            row = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def _validate_history(self, applied: dict[int, str]) -> None:
        known = {migration.version: migration.name for migration in self._migrations}
        for version, name in applied.items():
            if known.get(version) != name:
                raise RuntimeError(f"Unknown database migration {version}: {name}")
