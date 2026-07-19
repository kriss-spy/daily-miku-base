"""Minimal synchronous database seam shared by durable ledger components."""

from collections.abc import Callable
from threading import Lock
from types import TracebackType
from typing import Any, Protocol, Self, cast

import psycopg
from psycopg_pool import ConnectionPool


class QueryResult(Protocol):
    """Rows returned by the SQL surfaces used by the ledger."""

    def fetchone(self) -> tuple[Any, ...] | None:
        """Return one row if present."""
        ...

    def fetchall(self) -> list[tuple[Any, ...]]:
        """Return all rows."""
        ...


class DatabaseConnection(Protocol):
    """Context-managed transaction connection."""

    def __enter__(self) -> Self:
        """Begin a transaction scope."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> object:
        """Commit successful work or roll back failures."""
        ...

    def execute(self, query: str, params: tuple[object, ...] = ()) -> QueryResult:
        """Execute one SQL operation."""
        ...


ConnectionFactory = Callable[[], DatabaseConnection]


def postgres_connections(
    database_url: str, *, local_pool: bool = False
) -> ConnectionFactory:
    """Build serverless connections or a small lazy local pool."""
    if local_pool:
        return _local_pool(database_url)

    def connect() -> DatabaseConnection:
        return cast(DatabaseConnection, psycopg.connect(database_url))

    return connect


def _local_pool(database_url: str) -> ConnectionFactory:
    pool = ConnectionPool(database_url, min_size=0, max_size=4, open=False)
    open_lock = Lock()
    opened = False

    def connect() -> DatabaseConnection:
        nonlocal opened
        if not opened:
            with open_lock:
                if not opened:
                    pool.open()
                    opened = True
        return cast(DatabaseConnection, pool.connection())

    return connect
