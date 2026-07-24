"""Immutable content-addressed Blob store ports and adapters."""

from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from types import TracebackType
from typing import Protocol
from urllib.parse import urlparse

from vercel.blob import BlobClient
from vercel.blob.errors import (
    BlobError,
    BlobNotFoundError,
    BlobServiceNotAvailable,
    BlobServiceRateLimited,
    BlobUnknownError,
)

from .validate import MAX_OUTPUT_BYTES


class BlobDependencyError(RuntimeError):
    """Blob storage could not complete an operation."""

    def __init__(
        self,
        message: str,
        *,
        transient: bool = False,
        timeout: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.timeout = timeout
        self.retry_after = retry_after


@dataclass(frozen=True)
class BlobObject:
    """One immutable public object."""

    key: str
    url: str


class BlobStore(Protocol):
    """Store normalized bytes at a verified content-addressed key."""

    def put(self, key: str, data: bytes, content_type: str) -> BlobObject:
        """Idempotently store bytes and return their public identity."""
        ...

    def get(self, key: str) -> tuple[bytes, str]:
        """Read controlled bytes and their validated media type."""
        ...


class SDKBlobMetadata(Protocol):
    """Public Vercel SDK result fields used by this adapter."""

    url: str
    pathname: str
    content_type: str | None


class SDKBlobDownload(SDKBlobMetadata, Protocol):
    """Public Vercel SDK download fields used for collision verification."""

    content: bytes
    size: int | None


class SDKBlobHead(SDKBlobMetadata, Protocol):
    """Public Vercel SDK metadata fields used before downloading a collision."""

    size: int


class SDKBlobClient(Protocol):
    """Stable public ``BlobClient`` methods required by the adapter."""

    def __enter__(self) -> "SDKBlobClient": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> object: ...

    def put(
        self,
        path: str,
        body: bytes,
        *,
        access: str,
        content_type: str,
        add_random_suffix: bool,
        overwrite: bool,
        cache_control_max_age: int,
    ) -> SDKBlobMetadata: ...

    def head(self, url_or_path: str) -> SDKBlobHead: ...

    def get(
        self,
        url_or_path: str,
        *,
        access: str,
        timeout: float,
        use_cache: bool,
    ) -> SDKBlobDownload: ...


def verify_content_key(key: str, data: bytes) -> None:
    """Reject mutable or incorrectly addressed image writes."""
    digest = sha256(data).hexdigest()
    if key != f"images/{digest}.png":
        raise ValueError("Blob key must match the normalized content digest")


@dataclass
class InMemoryBlobStore:
    """Network-free adapter with production immutability semantics."""

    base_url: str = "https://blob.example.test"
    objects: dict[str, tuple[bytes, str]] = field(default_factory=dict)
    fail: bool = False

    def put(self, key: str, data: bytes, content_type: str) -> BlobObject:
        """Store once, allowing only an identical idempotent replay."""
        verify_content_key(key, data)
        if self.fail:
            raise BlobDependencyError("Blob storage is unavailable")
        existing = self.objects.get(key)
        if existing is not None and existing != (data, content_type):
            raise BlobDependencyError("Immutable Blob key already has other content")
        self.objects[key] = (data, content_type)
        return BlobObject(key, f"{self.base_url.rstrip('/')}/{key}")

    def get(self, key: str) -> tuple[bytes, str]:
        """Read bytes from the isolated immutable store."""
        if self.fail or key not in self.objects:
            raise BlobDependencyError("Blob content is unavailable")
        return self.objects[key]


@dataclass(frozen=True)
class VercelBlobStore:
    """Official Vercel Python SDK adapter for immutable public image objects."""

    token: str
    timeout: float = 15.0
    client_factory: Callable[[str], SDKBlobClient] = field(
        default=BlobClient, repr=False, compare=False
    )

    def put(self, key: str, data: bytes, content_type: str) -> BlobObject:
        """Upload content with immutable CDN caching and validate the response."""
        verify_content_key(key, data)
        try:
            with self.client_factory(self.token) as client:
                try:
                    result = client.put(
                        key,
                        data,
                        access="public",
                        content_type=content_type,
                        add_random_suffix=False,
                        overwrite=False,
                        cache_control_max_age=31_536_000,
                    )
                except BlobUnknownError as collision_or_unknown:
                    try:
                        return self._verify_existing(client, key, data, content_type)
                    except BlobNotFoundError:
                        raise _dependency_error(
                            collision_or_unknown
                        ) from collision_or_unknown
                url = _validated_blob_result(result, key, content_type)
        except BlobDependencyError:
            raise
        except BlobError as exc:
            raise _dependency_error(exc) from exc
        except (TypeError, ValueError) as exc:
            raise BlobDependencyError("Blob upload failed") from exc
        return BlobObject(key, url)

    def get(self, key: str) -> tuple[bytes, str]:
        """Download controlled bytes with bounded validation."""
        try:
            with self.client_factory(self.token) as client:
                result = client.get(
                    key, access="public", timeout=self.timeout, use_cache=True
                )
        except BlobError as exc:
            raise _dependency_error(exc) from exc
        content_type = (result.content_type or "").split(";", 1)[0]
        if result.pathname != key or content_type != "image/png":
            raise BlobDependencyError("Blob content failed validation")
        if result.size is None or result.size != len(result.content):
            raise BlobDependencyError("Blob content size failed validation")
        verify_content_key(key, result.content)
        return result.content, content_type

    def _verify_existing(
        self,
        client: SDKBlobClient,
        key: str,
        expected_data: bytes,
        content_type: str,
    ) -> BlobObject:
        """Accept a collision only after validating the existing immutable bytes."""
        metadata = client.head(key)
        url = _validated_blob_result(metadata, key, content_type)
        if metadata.size > MAX_OUTPUT_BYTES:
            raise ValueError("Existing Blob exceeds the normalized size limit")
        existing = client.get(
            url, access="public", timeout=self.timeout, use_cache=False
        )
        if existing.pathname != key or existing.url != url:
            raise ValueError("Existing Blob identity changed during verification")
        if (existing.content_type or "").split(";", 1)[0] != content_type:
            raise ValueError("Existing Blob has an unexpected content type")
        if existing.size is None or existing.size > MAX_OUTPUT_BYTES:
            raise ValueError("Existing Blob exceeds the normalized size limit")
        if len(existing.content) != existing.size:
            raise ValueError("Existing Blob size metadata does not match its bytes")
        if existing.content != expected_data:
            raise ValueError("Existing Blob bytes do not match the content address")
        return BlobObject(key, url)


def _validated_blob_result(result: SDKBlobMetadata, key: str, content_type: str) -> str:
    """Validate a public SDK result before persisting or redirecting to it."""
    url = result.url
    pathname = result.pathname
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("Blob response omitted a secure public URL")
    if not (urlparse(url).hostname or "").endswith(".blob.vercel-storage.com"):
        raise ValueError("Blob response URL was not controlled by Vercel Blob")
    if pathname != key:
        raise ValueError("Blob response pathname did not match the request")
    if (result.content_type or "").split(";", 1)[0] != content_type:
        raise ValueError("Blob response content type did not match the request")
    return url


def _dependency_error(exc: BlobError) -> BlobDependencyError:
    """Map public SDK errors onto the application's retry categories."""
    if isinstance(exc, BlobServiceRateLimited):
        retry_after = float(exc.retry_after) if 0 < exc.retry_after <= 2 else None
        return BlobDependencyError(
            "Blob upload failed",
            transient=retry_after is not None,
            retry_after=retry_after,
        )
    return BlobDependencyError(
        "Blob upload failed",
        transient=isinstance(exc, (BlobServiceNotAvailable, BlobUnknownError)),
    )
