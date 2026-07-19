"""Tests for environment-appropriate Postgres connection management."""

from typing import Any

import pytest

from daily_miku.ledger import database

pytestmark = pytest.mark.unit


class FakePool:
    """Observe lazy local pool lifecycle without opening a database."""

    def __init__(self, conninfo: str, **kwargs: object) -> None:
        self.conninfo = conninfo
        self.options = kwargs
        self.open_count = 0
        self.connection_count = 0

    def open(self) -> None:
        self.open_count += 1

    def connection(self) -> object:
        self.connection_count += 1
        return object()


class TestPostgresConnections:
    """Connection strategy differs between local and serverless execution."""

    def test_serverless_factory_opens_a_connection_per_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connections: list[object] = []

        def connect(database_url: str) -> object:
            connection = object()
            connections.append(connection)
            return connection

        monkeypatch.setattr(database.psycopg, "connect", connect)
        factory = database.postgres_connections("postgresql://serverless")

        assert factory() is connections[0]
        assert factory() is connections[1]
        assert len(connections) == 2

    def test_local_pool_opens_lazily_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pools: list[FakePool] = []

        def create_pool(conninfo: str, **kwargs: Any) -> FakePool:
            pool = FakePool(conninfo, **kwargs)
            pools.append(pool)
            return pool

        monkeypatch.setattr(database, "ConnectionPool", create_pool)
        factory = database.postgres_connections("postgresql://local", local_pool=True)

        assert pools[0].open_count == 0
        factory()
        factory()

        assert pools[0].open_count == 1
        assert pools[0].connection_count == 2
        assert pools[0].options == {"min_size": 0, "max_size": 4, "open": False}
