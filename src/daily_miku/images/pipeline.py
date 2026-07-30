"""Deep module for controlled image mutations and dated resolution."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from hashlib import sha256
from typing import TypeVar
from uuid import uuid4

from ..catalog import CatalogSlot, SlotCatalog
from ..content_source import ContentDependencyError, ContentFailure
from ..domain import Clock, SlotState
from .blob import BlobDependencyError, BlobStore
from .publisher import CoverDependencyError, CoverPublisher
from .retry import RetryPolicy
from .store import (
    ImageAlreadyWithdrawn,
    ImageProvenance,
    ImageRepository,
    ImageStoreDependencyError,
    ImageWithdrawal,
)
from .validate import UnsafeImage, normalize_raster

T = TypeVar("T")


def _new_ingest_id() -> str:
    """Return one operation identity reused only by retries of this ingestion."""
    return str(uuid4())


class ImageFailure(StrEnum):
    """Stable dependency failure categories exposed to delivery adapters."""

    UPSTREAM = "upstream"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"


class ImageDependencyError(RuntimeError):
    """A required image dependency failed with a stable class."""

    def __init__(self, message: str, kind: ImageFailure) -> None:
        super().__init__(message)
        self.kind = kind


class ImageBlocked(ValueError):
    """Valid domain or safety policy blocks an image mutation."""


class ImageResolutionKind(StrEnum):
    """Every contracted dated image resolution outcome."""

    REDIRECT = "redirect"
    NO_IMAGE = "no_image"
    CONFLICT = "conflict"
    WITHDRAWN = "withdrawn"
    UPSTREAM = "upstream"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class ImageResolution:
    """One stable image resolution outcome and optional redirect identity."""

    kind: ImageResolutionKind
    location: str | None = None
    digest: str | None = None


@dataclass(frozen=True)
class ImagePipeline:
    """Hide image safety, storage, audit, withdrawal, and resolution rules."""

    catalog: SlotCatalog
    repository: ImageRepository
    blob_store: BlobStore
    cover_publisher: CoverPublisher
    clock: Clock
    operator: str
    retry_policy: RetryPolicy = RetryPolicy()
    ingest_id_factory: Callable[[], str] = field(default=_new_ingest_id, repr=False)

    def ingest(
        self, raindrop_id: int, data: bytes, authorization_note: str
    ) -> ImageProvenance:
        """Validate and publish bytes, activating only after dependencies succeed."""
        if raindrop_id <= 0:
            raise ValueError("raindrop_id must be positive")
        note = authorization_note.strip()
        if not note:
            raise ValueError("authorization note must not be blank")
        try:
            normalized = normalize_raster(data)
        except UnsafeImage as exc:
            raise ImageBlocked(str(exc)) from exc
        try:
            if self.repository.withdrawal_for(raindrop_id) is not None:
                raise ImageBlocked("The image has been withdrawn.")
        except ImageStoreDependencyError as exc:
            raise ImageDependencyError(
                "Image ingestion dependency failed.", ImageFailure.UNAVAILABLE
            ) from exc
        digest = sha256(normalized.data).hexdigest()
        key = f"images/{digest}.{normalized.extension}"
        provenance = ImageProvenance(
            raindrop_id,
            self.ingest_id_factory(),
            digest,
            key,
            "",
            normalized.content_type,
            len(normalized.data),
            normalized.width,
            normalized.height,
            normalized.source_format,
            note,
            self.operator,
            self.clock.now(),
        )
        try:
            blob = self._retry(
                lambda: self.blob_store.put(
                    key, normalized.data, normalized.content_type
                )
            )
            provenance = replace(provenance, blob_url=blob.url)
            stage = self._retry(lambda: self.repository.stage(provenance))
            change = self._retry(
                lambda: self.cover_publisher.prepare_cover_change(raindrop_id, blob.url)
            )
            try:
                self._retry(lambda: self.cover_publisher.apply_cover(change))
            except CoverDependencyError:
                # A timed-out PUT may have succeeded remotely. Restore from the
                # pre-command snapshot before reporting that publication failed.
                self._retry(lambda: self.cover_publisher.restore_cover(change))
                raise
            try:
                return self._retry(lambda: self.repository.activate(stage))
            except (ImageAlreadyWithdrawn, ImageStoreDependencyError):
                self._retry(lambda: self.cover_publisher.restore_cover(change))
                raise
        except ImageAlreadyWithdrawn as exc:
            raise ImageBlocked(str(exc)) from exc
        except (
            BlobDependencyError,
            CoverDependencyError,
            ImageStoreDependencyError,
        ) as exc:
            kind = (
                ImageFailure.TIMEOUT
                if getattr(exc, "timeout", False)
                else ImageFailure.UNAVAILABLE
            )
            raise ImageDependencyError(
                "Image ingestion dependency failed.", kind
            ) from exc

    def withdraw(self, raindrop_id: int, reason: str) -> ImageWithdrawal:
        """Record an idempotent tombstone without deleting content-addressed bytes."""
        if raindrop_id <= 0 or not reason.strip():
            raise ValueError(
                "raindrop_id must be positive and reason must not be blank"
            )
        try:
            return self._retry(
                lambda: self.repository.withdraw(
                    ImageWithdrawal(
                        raindrop_id, reason.strip(), self.operator, self.clock.now()
                    )
                )
            )
        except ImageStoreDependencyError as exc:
            raise ImageDependencyError(
                "Image withdrawal dependency failed.", ImageFailure.UNAVAILABLE
            ) from exc

    def resolve_image(
        self, day: date, *, slot: CatalogSlot | None = None
    ) -> ImageResolution:
        """Resolve one date without forwarding unvalidated upstream bytes."""
        try:
            resolved_slot = slot or self.catalog.get_slot(day)
            if not resolved_slot.items:
                return ImageResolution(ImageResolutionKind.NO_IMAGE)
            if resolved_slot.state is SlotState.CONFLICT:
                return ImageResolution(ImageResolutionKind.CONFLICT)
            raindrop_id = resolved_slot.items[0].raindrop_id
            if self.repository.withdrawal_for(raindrop_id) is not None:
                return ImageResolution(ImageResolutionKind.WITHDRAWN)
            active = self.repository.active_for(raindrop_id)
            if active is not None:
                return ImageResolution(
                    ImageResolutionKind.REDIRECT, active.blob_url, active.digest
                )
            item = resolved_slot.items[0]
            if item.cover_identity:
                # Direct-cover: redirect to the Raindrop cover URL when no controlled
                # image is available. Controlled images remain preferred when present.
                return ImageResolution(ImageResolutionKind.REDIRECT, item.cover_identity)
            return ImageResolution(ImageResolutionKind.NO_IMAGE)
        except ContentDependencyError as exc:
            kind = {
                ContentFailure.UPSTREAM: ImageResolutionKind.UPSTREAM,
                ContentFailure.UNAVAILABLE: ImageResolutionKind.UNAVAILABLE,
                ContentFailure.TIMEOUT: ImageResolutionKind.TIMEOUT,
            }[exc.kind]
            return ImageResolution(kind)
        except ImageStoreDependencyError:
            return ImageResolution(ImageResolutionKind.UNAVAILABLE)

    def _retry(self, operation: Callable[[], T]) -> T:
        return self.retry_policy.run(
            operation, lambda exc: bool(getattr(exc, "transient", False))
        )
