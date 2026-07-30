"""Image provenance and withdrawal repository contracts and adapters."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Protocol

import psycopg
from psycopg_pool import PoolTimeout

from ..ledger.database import (
    ConnectionFactory,
    DatabaseConnection,
    postgres_connections,
)

logger = logging.getLogger("daily_miku.images.store")


class ImageStoreDependencyError(RuntimeError):
    """Image metadata storage could not complete an operation."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class ImageAlreadyWithdrawn(ValueError):
    """An image mutation attempted to bypass an existing tombstone."""


@dataclass(frozen=True)
class ImageProvenance:
    """Auditable facts for one normalized operator-supplied image."""

    raindrop_id: int
    ingest_id: str
    digest: str
    blob_key: str
    blob_url: str
    content_type: str
    byte_size: int
    width: int
    height: int
    source_format: str
    authorization_note: str
    operator: str
    ingested_at: datetime


@dataclass(frozen=True)
class ImageWithdrawal:
    """Durable delivery tombstone for one selected identity."""

    raindrop_id: int
    reason: str
    operator: str
    withdrawn_at: datetime


@dataclass(frozen=True)
class ImageStage:
    """Durable but non-deliverable provenance awaiting external publication."""

    stage_id: int
    provenance: ImageProvenance


class ImageRepository(Protocol):
    """Transaction boundary for active provenance and tombstones."""

    def stage(self, provenance: ImageProvenance) -> ImageStage:
        """Persist provenance without making it deliverable."""
        ...

    def activate(self, stage: ImageStage) -> ImageProvenance:
        """Atomically make staged provenance active unless tombstoned."""
        ...

    def active_for(self, raindrop_id: int) -> ImageProvenance | None:
        """Return the current controlled image, if any."""
        ...

    def withdrawal_for(self, raindrop_id: int) -> ImageWithdrawal | None:
        """Return a durable tombstone, if present."""
        ...

    def withdraw(self, withdrawal: ImageWithdrawal) -> ImageWithdrawal:
        """Atomically tombstone delivery without deleting shared bytes."""
        ...


@dataclass
class InMemoryImageRepository:
    """Thread-safe metadata fake retaining complete provenance history."""

    provenance: list[ImageProvenance] = field(default_factory=list)
    active: dict[int, ImageProvenance] = field(default_factory=dict)
    withdrawals: dict[int, ImageWithdrawal] = field(default_factory=dict)
    fail: bool = False
    fail_stage: bool = False
    fail_activate: bool = False
    _next_stage_id: int = 1
    stages: dict[int, ImageProvenance] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def stage(self, provenance: ImageProvenance) -> ImageStage:
        """Persist an inactive provenance record under the per-item lock."""
        with self._lock:
            self._check()
            if self.fail_stage:
                raise ImageStoreDependencyError(
                    "Image staging is unavailable", transient=True
                )
            if provenance.raindrop_id in self.withdrawals:
                raise ImageAlreadyWithdrawn("The image has been withdrawn.")
            for stage_id, existing in self.stages.items():
                if existing.ingest_id == provenance.ingest_id:
                    if existing != provenance:
                        raise ImageStoreDependencyError(
                            "Ingest identity was reused with different provenance"
                        )
                    return ImageStage(stage_id, existing)
            self.provenance.append(provenance)
            stage = ImageStage(self._next_stage_id, provenance)
            self._next_stage_id += 1
            self.stages[stage.stage_id] = provenance
            return stage

    def activate(self, stage: ImageStage) -> ImageProvenance:
        """Activate one known stage under the same per-item lock as withdrawal."""
        with self._lock:
            self._check()
            if self.fail_activate:
                raise ImageStoreDependencyError(
                    "Image activation is unavailable", transient=True
                )
            provenance = self.stages.get(stage.stage_id)
            if provenance is None or provenance != stage.provenance:
                raise ImageStoreDependencyError("Unknown image stage")
            if provenance.raindrop_id in self.withdrawals:
                raise ImageAlreadyWithdrawn("The image has been withdrawn.")
            self.active[provenance.raindrop_id] = provenance
            return provenance

    def active_for(self, raindrop_id: int) -> ImageProvenance | None:
        """Return active fake provenance without exposing staged records."""
        self._check()
        return self.active.get(raindrop_id)

    def withdrawal_for(self, raindrop_id: int) -> ImageWithdrawal | None:
        """Return a fake durable tombstone when one exists."""
        self._check()
        return self.withdrawals.get(raindrop_id)

    def withdraw(self, withdrawal: ImageWithdrawal) -> ImageWithdrawal:
        """Serialize tombstoning with staging and activation."""
        with self._lock:
            self._check()
            existing = self.withdrawals.get(withdrawal.raindrop_id)
            if existing is not None:
                return existing
            self.withdrawals[withdrawal.raindrop_id] = withdrawal
            self.active.pop(withdrawal.raindrop_id, None)
            return withdrawal

    def _check(self) -> None:
        if self.fail:
            raise ImageStoreDependencyError("Image metadata storage is unavailable")


@dataclass(frozen=True)
class PostgresImageRepository:
    """Postgres adapter for transactional provenance activation and withdrawal."""

    connection_factory: ConnectionFactory

    @classmethod
    def from_url(
        cls, database_url: str, *, local_pool: bool = False
    ) -> "PostgresImageRepository":
        """Build a repository from a pooled Postgres URL."""
        return cls(postgres_connections(database_url, local_pool=local_pool))

    def stage(self, provenance: ImageProvenance) -> ImageStage:
        """Serialize and persist provenance without changing delivery state."""
        try:
            with self.connection_factory() as connection:
                self._lock_identity(connection, provenance.raindrop_id)
                tombstone = connection.execute(
                    "SELECT raindrop_id FROM image_withdrawals "
                    "WHERE raindrop_id = %s FOR UPDATE",
                    (provenance.raindrop_id,),
                ).fetchone()
                if tombstone is not None:
                    raise ImageAlreadyWithdrawn("The image has been withdrawn.")
                row = connection.execute(
                    "INSERT INTO image_provenance (raindrop_id, ingest_id, digest, "
                    "blob_key, blob_url, content_type, byte_size, width, height, "
                    "source_format, authorization_note, operator, ingested_at) VALUES "
                    "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (ingest_id) DO NOTHING "
                    "RETURNING provenance_id",
                    (
                        provenance.raindrop_id,
                        provenance.ingest_id,
                        provenance.digest,
                        provenance.blob_key,
                        provenance.blob_url,
                        provenance.content_type,
                        provenance.byte_size,
                        provenance.width,
                        provenance.height,
                        provenance.source_format,
                        provenance.authorization_note,
                        provenance.operator,
                        provenance.ingested_at,
                    ),
                ).fetchone()
                if row is None:
                    row = connection.execute(
                        "SELECT provenance_id, raindrop_id, ingest_id::text, digest, "
                        "blob_key, blob_url, content_type, byte_size, width, height, "
                        "source_format, authorization_note, operator, ingested_at "
                        "FROM image_provenance WHERE ingest_id = %s",
                        (provenance.ingest_id,),
                    ).fetchone()
                    if row is None or ImageProvenance(*row[1:]) != provenance:
                        raise ImageStoreDependencyError(
                            "Ingest identity was reused with different provenance"
                        )
        except (psycopg.OperationalError, PoolTimeout) as exc:
            raise ImageStoreDependencyError(
                "Could not stage image metadata", transient=True
            ) from exc
        except psycopg.Error as exc:
            raise ImageStoreDependencyError("Could not stage image metadata") from exc
        return ImageStage(int(row[0]), provenance)

    def activate(self, stage: ImageStage) -> ImageProvenance:
        """Serialize activation with withdrawal, including the no-row case."""
        provenance = stage.provenance
        try:
            with self.connection_factory() as connection:
                self._lock_identity(connection, provenance.raindrop_id)
                tombstone = connection.execute(
                    "SELECT raindrop_id FROM image_withdrawals WHERE raindrop_id = %s",
                    (provenance.raindrop_id,),
                ).fetchone()
                if tombstone is not None:
                    raise ImageAlreadyWithdrawn("The image has been withdrawn.")
                staged = connection.execute(
                    "SELECT raindrop_id FROM image_provenance "
                    "WHERE provenance_id = %s AND raindrop_id = %s",
                    (stage.stage_id, provenance.raindrop_id),
                ).fetchone()
                if staged is None:
                    raise ImageStoreDependencyError("Unknown image stage")
                connection.execute(
                    "INSERT INTO active_images (raindrop_id, provenance_id) "
                    "VALUES (%s, %s) ON CONFLICT (raindrop_id) DO UPDATE SET "
                    "provenance_id = EXCLUDED.provenance_id",
                    (provenance.raindrop_id, stage.stage_id),
                )
        except (psycopg.OperationalError, PoolTimeout) as exc:
            raise ImageStoreDependencyError(
                "Could not activate image metadata", transient=True
            ) from exc
        except psycopg.Error as exc:
            raise ImageStoreDependencyError(
                "Could not activate image metadata"
            ) from exc
        return provenance

    def active_for(self, raindrop_id: int) -> ImageProvenance | None:
        """Read active provenance while excluding inactive stages."""
        query = (
            "SELECT p.raindrop_id, p.ingest_id::text, p.digest, p.blob_key, p.blob_url, "
            "p.content_type, p.byte_size, p.width, p.height, p.source_format, "
            "p.authorization_note, p.operator, p.ingested_at FROM active_images a "
            "JOIN image_provenance p ON p.provenance_id = a.provenance_id "
            "WHERE a.raindrop_id = %s"
        )
        try:
            with self.connection_factory() as connection:
                row = connection.execute(query, (raindrop_id,)).fetchone()
        except (psycopg.Error, PoolTimeout) as exc:
            logger.warning(
                "active_for failed for raindrop_id=%s: %s",
                raindrop_id,
                exc,
                exc_info=True,
            )
            raise ImageStoreDependencyError("Could not read image metadata") from exc
        return ImageProvenance(*row) if row is not None else None

    def withdrawal_for(self, raindrop_id: int) -> ImageWithdrawal | None:
        """Read one durable withdrawal tombstone."""
        try:
            with self.connection_factory() as connection:
                row = connection.execute(
                    "SELECT raindrop_id, reason, operator, withdrawn_at "
                    "FROM image_withdrawals WHERE raindrop_id = %s",
                    (raindrop_id,),
                ).fetchone()
        except (psycopg.Error, PoolTimeout) as exc:
            logger.warning(
                "withdrawal_for failed for raindrop_id=%s: %s",
                raindrop_id,
                exc,
                exc_info=True,
            )
            raise ImageStoreDependencyError("Could not read image withdrawal") from exc
        return ImageWithdrawal(*row) if row is not None else None

    def withdraw(self, withdrawal: ImageWithdrawal) -> ImageWithdrawal:
        """Serialize a tombstone against stage activation for the same identity."""
        try:
            with self.connection_factory() as connection:
                self._lock_identity(connection, withdrawal.raindrop_id)
                row = connection.execute(
                    "INSERT INTO image_withdrawals "
                    "(raindrop_id, reason, operator, withdrawn_at) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT (raindrop_id) DO NOTHING "
                    "RETURNING raindrop_id, reason, operator, withdrawn_at",
                    (
                        withdrawal.raindrop_id,
                        withdrawal.reason,
                        withdrawal.operator,
                        withdrawal.withdrawn_at,
                    ),
                ).fetchone()
                connection.execute(
                    "DELETE FROM active_images WHERE raindrop_id = %s",
                    (withdrawal.raindrop_id,),
                )
                if row is None:
                    row = connection.execute(
                        "SELECT raindrop_id, reason, operator, withdrawn_at "
                        "FROM image_withdrawals WHERE raindrop_id = %s",
                        (withdrawal.raindrop_id,),
                    ).fetchone()
        except (psycopg.OperationalError, PoolTimeout) as exc:
            raise ImageStoreDependencyError(
                "Could not withdraw image", transient=True
            ) from exc
        except psycopg.Error as exc:
            raise ImageStoreDependencyError("Could not withdraw image") from exc
        if row is None:
            raise ImageStoreDependencyError("Withdrawal was not persisted")
        return ImageWithdrawal(*row)

    @staticmethod
    def _lock_identity(connection: DatabaseConnection, raindrop_id: int) -> None:
        # Transaction-scoped advisory locking works even when no metadata row exists.
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (raindrop_id,))
