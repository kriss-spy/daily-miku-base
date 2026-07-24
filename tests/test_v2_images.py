"""Contract tests for controlled image ingestion, storage, and delivery."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from types import TracebackType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from vercel.blob.errors import (
    BlobAccessError,
    BlobError,
    BlobServiceNotAvailable,
    BlobServiceRateLimited,
    BlobUnknownError,
)
from vercel.blob.types import GetBlobResult, HeadBlobResult, PutBlobResult

from daily_miku import cli, main
from daily_miku.catalog import SlotCatalog
from daily_miku.config import Settings
from daily_miku.content_source import ContentFailure, InMemoryContentSource, TaggedItem
from daily_miku.domain import (
    Calendar,
    FixedClock,
    RecordingMethod,
    SelectionDay,
    SlotCandidate,
)
from daily_miku.http import create_app
from daily_miku.images import ImagePipeline
from daily_miku.images.blob import (
    BlobDependencyError,
    BlobObject,
    InMemoryBlobStore,
    VercelBlobStore,
)
from daily_miku.images.publisher import (
    CoverChange,
    CoverDependencyError,
    InMemoryCoverPublisher,
)
from daily_miku.images.retry import RetryPolicy
from daily_miku.images.store import (
    ImageStage,
    ImageStoreDependencyError,
    ImageProvenance,
    ImageWithdrawal,
    InMemoryImageRepository,
    PostgresImageRepository,
)
from daily_miku.images.validate import UnsafeImage, normalize_raster
from daily_miku.ledger.memory import InMemoryLedger
from daily_miku.services import build_services

pytestmark = pytest.mark.unit
NOW = datetime(2026, 7, 19, tzinfo=timezone.utc)


def raster_bytes(
    image_format: str = "PNG", *, size: tuple[int, int] = (3, 2), metadata: bool = False
) -> bytes:
    """Create a tiny fully decoded raster fixture."""
    output = BytesIO()
    image = Image.new("RGB", size, (16, 32, 64))
    pnginfo = None
    if metadata:
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("private", "must be stripped")
    image.save(output, format=image_format, pnginfo=pnginfo)
    return output.getvalue()


def image_pipeline(
    *,
    items: tuple[TaggedItem, ...] = (TaggedItem(7, title="Seven"),),
    conflict: bool = False,
) -> tuple[
    ImagePipeline,
    InMemoryLedger,
    InMemoryImageRepository,
    InMemoryBlobStore,
    InMemoryCoverPublisher,
]:
    """Build the full image capability without external services."""
    ledger = InMemoryLedger()
    day = SelectionDay(date(2026, 7, 18))
    ledger.record_candidate(day, SlotCandidate(7, RecordingMethod.OBSERVED, NOW))
    if conflict:
        ledger.record_candidate(day, SlotCandidate(8, RecordingMethod.MANUAL, NOW))
    repository = InMemoryImageRepository()
    blob = InMemoryBlobStore()
    publisher = InMemoryCoverPublisher()
    source = InMemoryContentSource(items)
    catalog = SlotCatalog(
        ledger, Calendar.named("Asia/Shanghai"), FixedClock(NOW), source
    )
    pipeline = ImagePipeline(
        catalog,
        repository,
        blob,
        publisher,
        FixedClock(NOW),
        "operator",
        RetryPolicy(sleep=lambda _: None, jitter=lambda: 0),
    )
    return pipeline, ledger, repository, blob, publisher


@pytest.mark.parametrize(
    "data",
    [b"<html>not an image</html>", b'{"error":true}', b"\x89PNG\r\ncorrupt"],
)
def test_decode_validation_rejects_non_images(data: bytes) -> None:
    with pytest.raises(UnsafeImage):
        normalize_raster(data)


def test_validation_normalizes_type_and_strips_metadata() -> None:
    normalized = normalize_raster(raster_bytes("PNG", metadata=True))

    assert normalized.content_type == "image/png"
    assert normalized.extension == "png"
    assert normalized.source_format == "PNG"
    with Image.open(BytesIO(normalized.data)) as decoded:
        assert decoded.size == (3, 2)
        assert "private" not in decoded.info


def test_validation_rejects_unsupported_and_oversized_dimensions() -> None:
    with pytest.raises(UnsafeImage, match="Only JPEG"):
        normalize_raster(raster_bytes("GIF"))
    with pytest.raises(UnsafeImage, match="dimensions"):
        normalize_raster(raster_bytes("PNG", size=(8193, 1)))


def test_blob_adapter_enforces_content_addressed_immutability() -> None:
    normalized = normalize_raster(raster_bytes())
    from hashlib import sha256

    key = f"images/{sha256(normalized.data).hexdigest()}.png"
    blob = InMemoryBlobStore()
    first = blob.put(key, normalized.data, normalized.content_type)
    second = blob.put(key, normalized.data, normalized.content_type)

    assert first == second
    assert len(blob.objects) == 1
    with pytest.raises(ValueError, match="content digest"):
        blob.put("images/wrong.png", normalized.data, normalized.content_type)


class FakeSDKBlobClient:
    """Fake only the stable public ``vercel.blob.BlobClient`` contract."""

    def __init__(
        self,
        put_result: PutBlobResult | BlobError,
        *,
        head_result: HeadBlobResult | BlobError | None = None,
        get_result: GetBlobResult | BlobError | None = None,
    ) -> None:
        self.put_result = put_result
        self.head_result = head_result
        self.get_result = get_result
        self.put_calls: list[tuple[str, bytes, dict[str, object]]] = []
        self.head_calls: list[str] = []
        self.get_calls: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def __enter__(self) -> "FakeSDKBlobClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True

    def put(self, path: str, body: bytes, **kwargs: object) -> PutBlobResult:
        """Record SDK upload options and return or raise the configured result."""
        self.put_calls.append((path, body, kwargs))
        if isinstance(self.put_result, BlobError):
            raise self.put_result
        return self.put_result

    def head(self, url_or_path: str) -> HeadBlobResult:
        """Return configured SDK metadata for collision verification."""
        self.head_calls.append(url_or_path)
        if isinstance(self.head_result, BlobError):
            raise self.head_result
        assert self.head_result is not None
        return self.head_result

    def get(self, url_or_path: str, **kwargs: object) -> GetBlobResult:
        """Return configured SDK bytes for collision verification."""
        self.get_calls.append((url_or_path, kwargs))
        if isinstance(self.get_result, BlobError):
            raise self.get_result
        assert self.get_result is not None
        return self.get_result


def sdk_results(
    key: str, data: bytes, content_type: str = "image/png"
) -> tuple[PutBlobResult, HeadBlobResult, GetBlobResult]:
    """Create consistent public SDK result objects for one Blob."""
    url = f"https://store.public.blob.vercel-storage.com/{key}"
    download_url = f"{url}?download=1"
    uploaded_at = NOW
    return (
        PutBlobResult(url, download_url, key, content_type, "inline"),
        HeadBlobResult(
            len(data),
            uploaded_at,
            key,
            content_type,
            "inline",
            url,
            download_url,
            "public, max-age=31536000",
        ),
        GetBlobResult(
            url,
            download_url,
            key,
            content_type,
            len(data),
            "inline",
            "public, max-age=31536000",
            uploaded_at,
            '"etag"',
            data,
            200,
        ),
    )


def test_vercel_blob_adapter_uses_official_sdk_immutable_options() -> None:
    normalized = normalize_raster(raster_bytes())
    from hashlib import sha256

    key = f"images/{sha256(normalized.data).hexdigest()}.png"
    uploaded, _, _ = sdk_results(key, normalized.data)
    client = FakeSDKBlobClient(uploaded)
    tokens: list[str] = []

    result = VercelBlobStore(
        "secret", client_factory=lambda token: tokens.append(token) or client
    ).put(key, normalized.data, normalized.content_type)

    assert result == BlobObject(key, uploaded.url)
    assert tokens == ["secret"]
    assert client.put_calls == [
        (
            key,
            normalized.data,
            {
                "access": "public",
                "content_type": "image/png",
                "add_random_suffix": False,
                "overwrite": False,
                "cache_control_max_age": 31_536_000,
            },
        )
    ]
    assert client.closed


def test_vercel_blob_collision_accepts_only_verified_idempotent_replay() -> None:
    """Resolve an SDK conflict through public head/get byte verification."""
    normalized = normalize_raster(raster_bytes())
    from hashlib import sha256

    key = f"images/{sha256(normalized.data).hexdigest()}.png"
    _, metadata, existing = sdk_results(key, normalized.data)
    client = FakeSDKBlobClient(
        BlobUnknownError(), head_result=metadata, get_result=existing
    )
    store = VercelBlobStore("secret", client_factory=lambda _: client)

    result = store.put(key, normalized.data, "image/png")

    assert result == BlobObject(key, metadata.url)
    assert client.head_calls == [key]
    assert client.get_calls == [
        (
            metadata.url,
            {"access": "public", "timeout": 15.0, "use_cache": False},
        )
    ]


def test_vercel_blob_collision_rejects_unknown_existing_bytes() -> None:
    """Never overwrite or trust bytes merely because their pathname is addressed."""
    normalized = normalize_raster(raster_bytes())
    from hashlib import sha256

    key = f"images/{sha256(normalized.data).hexdigest()}.png"
    _, metadata, existing = sdk_results(key, b"unknown bytes")
    client = FakeSDKBlobClient(
        BlobUnknownError(), head_result=metadata, get_result=existing
    )

    with pytest.raises(BlobDependencyError, match="upload failed") as error:
        VercelBlobStore("secret", client_factory=lambda _: client).put(
            key, normalized.data, "image/png"
        )

    assert error.value.transient is False


@pytest.mark.parametrize(
    ("sdk_error", "transient", "retry_after"),
    [
        (BlobServiceNotAvailable(), True, None),
        (BlobServiceRateLimited(), False, None),
        (BlobServiceRateLimited(1), True, 1.0),
        (BlobAccessError(), False, None),
    ],
)
def test_blob_adapter_maps_only_public_sdk_transient_categories(
    sdk_error: BlobError,
    transient: bool,
    retry_after: float | None,
) -> None:
    """Classify public SDK availability/rate errors without inspecting HTTP."""
    normalized = normalize_raster(raster_bytes())
    from hashlib import sha256

    key = f"images/{sha256(normalized.data).hexdigest()}.png"
    client = FakeSDKBlobClient(sdk_error)

    with pytest.raises(BlobDependencyError) as error:
        VercelBlobStore("secret", client_factory=lambda _: client).put(
            key, normalized.data, "image/png"
        )

    assert error.value.transient is transient
    assert error.value.retry_after == retry_after


class FakeResult:
    """Minimal psycopg result for image adapter contract tests."""

    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self.row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [self.row] if self.row is not None else []


class ScriptedConnection:
    """Transaction-shaped connection returning ordered scripted rows."""

    def __init__(self, rows: list[tuple[object, ...] | None]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "ScriptedConnection":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.queries.append((query, params))
        return FakeResult(self.rows.pop(0) if self.rows else None)


def provenance() -> ImageProvenance:
    """Create a valid durable image record fixture."""
    digest = "a" * 64
    return ImageProvenance(
        7,
        "00000000-0000-0000-0000-000000000007",
        digest,
        f"images/{digest}.png",
        f"https://blob.example/images/{digest}.png",
        "image/png",
        100,
        3,
        2,
        "PNG",
        "creator permission",
        "operator",
        NOW,
    )


def test_postgres_image_adapter_activates_in_one_transaction_and_maps_reads() -> None:
    record = provenance()
    stage_write = ScriptedConnection([None, None, (41,)])
    repository = PostgresImageRepository(lambda: stage_write)

    stage = repository.stage(record)

    assert stage == ImageStage(41, record)
    assert "pg_advisory_xact_lock" in stage_write.queries[0][0]
    assert stage_write.queries[0][1] == (7,)
    assert "FOR UPDATE" in stage_write.queries[1][0]
    assert "INSERT INTO image_provenance" in stage_write.queries[2][0]

    activate = ScriptedConnection([None, None, (7,), None])
    assert PostgresImageRepository(lambda: activate).activate(stage) == record
    assert "pg_advisory_xact_lock" in activate.queries[0][0]
    assert activate.queries[0][1] == (7,)
    assert "INSERT INTO active_images" in activate.queries[3][0]

    read = ScriptedConnection([tuple(record.__dict__.values())])
    assert PostgresImageRepository(lambda: read).active_for(7) == record


def test_postgres_staging_replay_returns_the_persisted_audit_facts() -> None:
    """A transaction retry reuses its ingest ID and exact persisted provenance."""
    record = provenance()
    persisted = (41, *record.__dict__.values())
    replay = ScriptedConnection([None, None, None, persisted])

    stage = PostgresImageRepository(lambda: replay).stage(record)

    assert stage == ImageStage(41, record)
    assert "ON CONFLICT (ingest_id) DO NOTHING" in replay.queries[2][0]
    assert "WHERE ingest_id" in replay.queries[3][0]


def test_staging_is_retry_idempotent_but_same_digest_commands_are_append_only() -> None:
    """Preserve each command's authorization facts while deduplicating its retries."""
    repository = InMemoryImageRepository()
    first = provenance()
    first_stage = repository.stage(first)

    assert repository.stage(first) == first_stage
    second = replace(
        first,
        ingest_id="00000000-0000-0000-0000-000000000008",
        authorization_note="separate renewed permission",
        operator="second-operator",
        ingested_at=NOW + timedelta(minutes=1),
    )
    second_stage = repository.stage(second)

    assert second_stage.stage_id != first_stage.stage_id
    assert repository.provenance == [first, second]
    with pytest.raises(ImageStoreDependencyError, match="different provenance"):
        repository.stage(replace(first, authorization_note="inconsistent retry"))


def test_postgres_image_adapter_persists_idempotent_withdrawal() -> None:
    withdrawal = ImageWithdrawal(7, "rights request", "operator", NOW)
    row = tuple(withdrawal.__dict__.values())
    first = ScriptedConnection([None, row, None])
    existing = ScriptedConnection([None, None, None, row])

    assert PostgresImageRepository(lambda: first).withdraw(withdrawal) == withdrawal
    assert PostgresImageRepository(lambda: existing).withdraw(withdrawal) == withdrawal
    assert "pg_advisory_xact_lock" in first.queries[0][0]
    assert first.queries[0][1] == (7,)
    assert "DELETE FROM active_images" in first.queries[2][0]
    assert "SELECT raindrop_id" in existing.queries[3][0]


def test_activate_and_withdraw_use_the_same_lock_when_metadata_rows_are_absent() -> (
    None
):
    record = provenance()
    stage = ImageStage(41, record)
    activate = ScriptedConnection([None, None, None])
    withdraw = ScriptedConnection([None, None, None, (7, "reason", "operator", NOW)])

    with pytest.raises(ImageStoreDependencyError, match="Unknown image stage"):
        PostgresImageRepository(lambda: activate).activate(stage)
    PostgresImageRepository(lambda: withdraw).withdraw(
        ImageWithdrawal(7, "reason", "operator", NOW)
    )

    assert activate.queries[0] == withdraw.queries[0]
    assert activate.queries[0][1] == (7,)


def test_ingest_records_authorization_and_activates_after_dependencies() -> None:
    pipeline, _, repository, blob, publisher = image_pipeline()

    record = pipeline.ingest(7, raster_bytes("JPEG"), "Creator granted permission")

    assert record.authorization_note == "Creator granted permission"
    assert record.operator == "operator"
    assert record.blob_key == f"images/{record.digest}.png"
    assert repository.active_for(7) == record
    assert publisher.covers[7] == record.blob_url
    assert blob.objects[record.blob_key][1] == "image/png"


def test_failed_cover_update_does_not_activate_delivery() -> None:
    pipeline, _, repository, blob, publisher = image_pipeline()
    publisher.fail = True

    from daily_miku.images import ImageDependencyError

    with pytest.raises(ImageDependencyError, match="dependency failed"):
        pipeline.ingest(7, raster_bytes(), "authorized")

    assert repository.active_for(7) is None
    assert len(blob.objects) == 1  # safe content-addressed orphan, never delivered


def test_activation_failure_compensates_external_cover_mutation() -> None:
    pipeline, _, repository, _, publisher = image_pipeline()
    publisher.covers[7] = "https://former.example/cover.png"
    repository.fail_activate = True

    from daily_miku.images import ImageDependencyError

    with pytest.raises(ImageDependencyError, match="dependency failed"):
        pipeline.ingest(7, raster_bytes(), "authorized")

    assert repository.active_for(7) is None
    assert publisher.covers[7] == "https://former.example/cover.png"
    assert publisher.set_count == 1
    assert publisher.restore_count == 1


class LostResponseCoverPublisher(InMemoryCoverPublisher):
    """Apply a cover remotely and then simulate a lost successful response."""

    lost_responses: int

    def __init__(self, lost_responses: int) -> None:
        super().__init__()
        self.lost_responses = lost_responses

    def apply_cover(self, change: CoverChange) -> None:
        """Mutate first, then fail transiently to model an ambiguous PUT result."""
        super().apply_cover(change)
        if self.lost_responses:
            self.lost_responses -= 1
            raise CoverDependencyError("response lost", transient=True)


def test_cover_retry_and_activation_compensation_keep_original_snapshot() -> None:
    """Never replace compensation facts by re-reading after an ambiguous PUT."""
    pipeline, _, repository, _, _ = image_pipeline()
    publisher = LostResponseCoverPublisher(1)
    publisher.covers[7] = "https://original.example/cover.png"
    repository.fail_activate = True
    object.__setattr__(pipeline, "cover_publisher", publisher)

    from daily_miku.images import ImageDependencyError

    with pytest.raises(ImageDependencyError):
        pipeline.ingest(7, raster_bytes(), "authorized")

    assert publisher.set_count == 2
    assert publisher.restore_count == 1
    assert publisher.covers[7] == "https://original.example/cover.png"


def test_exhausted_ambiguous_cover_put_restores_original_before_failure() -> None:
    """Compensate even when all three PUT responses are lost after mutation."""
    pipeline, _, repository, _, _ = image_pipeline()
    publisher = LostResponseCoverPublisher(3)
    publisher.covers[7] = "https://original.example/cover.png"
    object.__setattr__(pipeline, "cover_publisher", publisher)

    from daily_miku.images import ImageDependencyError

    with pytest.raises(ImageDependencyError):
        pipeline.ingest(7, raster_bytes(), "authorized")

    assert publisher.set_count == 3
    assert publisher.restore_count == 1
    assert publisher.covers[7] == "https://original.example/cover.png"
    assert repository.active_for(7) is None


class FlakyBlobStore(InMemoryBlobStore):
    """Blob fake that fails a configurable number of transient attempts."""

    def __init__(self, failures: int, *, transient: bool = True) -> None:
        super().__init__()
        self.failures = failures
        self.transient = transient
        self.attempts = 0

    def put(self, key: str, data: bytes, content_type: str) -> BlobObject:
        """Fail before delegating until the configured attempt threshold."""
        self.attempts += 1
        if self.attempts <= self.failures:
            raise BlobDependencyError("injected blob failure", transient=self.transient)
        return super().put(key, data, content_type)


def test_transient_operations_retry_at_most_three_times_with_bounded_delays() -> None:
    pipeline, _, _, _, _ = image_pipeline()
    blob = FlakyBlobStore(2)
    delays: list[float] = []
    object.__setattr__(pipeline, "blob_store", blob)
    object.__setattr__(
        pipeline,
        "retry_policy",
        RetryPolicy(sleep=delays.append, jitter=lambda: 1),
    )

    pipeline.ingest(7, raster_bytes(), "authorized")

    assert blob.attempts == 3
    assert delays == [0.25, 0.5]
    assert all(delay <= 2 for delay in delays)


def test_non_transient_operations_are_never_retried() -> None:
    pipeline, _, repository, _, _ = image_pipeline()
    blob = FlakyBlobStore(3, transient=False)
    delays: list[float] = []
    object.__setattr__(pipeline, "blob_store", blob)
    object.__setattr__(
        pipeline,
        "retry_policy",
        RetryPolicy(sleep=delays.append, jitter=lambda: 1),
    )

    from daily_miku.images import ImageDependencyError

    with pytest.raises(ImageDependencyError):
        pipeline.ingest(7, raster_bytes(), "authorized")

    assert blob.attempts == 1
    assert delays == []
    assert repository.provenance == []


def test_exhausted_transient_operation_stops_after_three_attempts() -> None:
    pipeline, _, repository, _, _ = image_pipeline()
    blob = FlakyBlobStore(5, transient=True)
    delays: list[float] = []
    object.__setattr__(pipeline, "blob_store", blob)
    object.__setattr__(
        pipeline,
        "retry_policy",
        RetryPolicy(sleep=delays.append, jitter=lambda: 1),
    )

    from daily_miku.images import ImageDependencyError

    with pytest.raises(ImageDependencyError):
        pipeline.ingest(7, raster_bytes(), "authorized")

    assert blob.attempts == 3
    assert delays == [0.25, 0.5]
    assert repository.provenance == []


def test_withdrawal_is_durable_and_never_deletes_shared_blob() -> None:
    pipeline, _, repository, blob, _ = image_pipeline()
    first = pipeline.ingest(7, raster_bytes(), "authorized")
    second_pipeline, _, second_repository, _, _ = image_pipeline(
        items=(TaggedItem(7, title="Seven"),)
    )
    # Model another item reference by retaining the same immutable bytes externally.
    second_repository.active[9] = first

    tombstone = pipeline.withdraw(7, "Rights holder request")

    assert tombstone.reason == "Rights holder request"
    assert repository.withdrawal_for(7) == tombstone
    assert repository.active_for(7) is None
    assert first.blob_key in blob.objects
    assert second_repository.active_for(9) == first
    assert pipeline.resolve_image(date(2026, 7, 18)).kind.value == "withdrawn"


def image_client(
    *,
    selected: bool = True,
    conflict: bool = False,
    cover: str | None = None,
    lookup_failure: ContentFailure | None = None,
    repository_failure: bool = False,
    ingest: bool = False,
    withdraw: bool = False,
) -> TestClient:
    """Build an isolated HTTP client for one configured image outcome."""
    settings = Settings.in_memory()
    ledger = InMemoryLedger()
    day = SelectionDay(date(2026, 7, 18))
    items: list[TaggedItem] = []
    if selected:
        ledger.record_candidate(day, SlotCandidate(7, RecordingMethod.OBSERVED, NOW))
        items.append(TaggedItem(7, cover_identity=cover, title="Seven"))
    if conflict:
        ledger.record_candidate(day, SlotCandidate(8, RecordingMethod.MANUAL, NOW))
        items.append(TaggedItem(8, title="Eight"))
    source = InMemoryContentSource(tuple(items), lookup_failure=lookup_failure)
    repository = InMemoryImageRepository(fail=repository_failure)
    blob = InMemoryBlobStore()
    publisher = InMemoryCoverPublisher()
    services = build_services(
        settings,
        clock=FixedClock(NOW),
        ledger=ledger,
        content_source=source,
        image_repository=repository,
        blob_store=blob,
        cover_publisher=publisher,
    )
    if ingest:
        services.images.ingest(7, raster_bytes(), "authorized")
    if withdraw:
        services.images.withdraw(7, "withdrawn")
    return TestClient(create_app(services=services))


@pytest.mark.parametrize(
    ("client", "path", "status", "code", "cache"),
    [
        (image_client(), "/image/not-a-date", 400, "date_malformed", "no-store"),
        (
            image_client(selected=False),
            "/image/2026-07-18",
            404,
            "image_not_found",
            "public",
        ),
        (image_client(), "/image/2026-07-18", 404, "image_not_found", "public"),
        (
            image_client(conflict=True),
            "/image/2026-07-18",
            409,
            "slot_conflict",
            "public",
        ),
        (
            image_client(withdraw=True),
            "/image/2026-07-18",
            410,
            "image_withdrawn",
            "public",
        ),
        (
            image_client(cover="https://upstream.test/a"),
            "/image/2026-07-18",
            502,
            "image_upstream_failed",
            "no-store",
        ),
        (
            image_client(repository_failure=True),
            "/image/2026-07-18",
            503,
            "image_unavailable",
            "no-store",
        ),
        (
            image_client(lookup_failure=ContentFailure.TIMEOUT),
            "/image/2026-07-18",
            504,
            "image_timeout",
            "no-store",
        ),
    ],
)
def test_image_http_outcomes_and_cache_contract(
    client: TestClient, path: str, status: int, code: str, cache: str
) -> None:
    response = client.get(path)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert cache in response.headers["Cache-Control"]
    assert response.headers.get("content-type", "").startswith("application/json")


def test_image_http_redirect_is_mutable_and_validated() -> None:
    response = image_client(ingest=True).get(
        "/image/2026-07-18", follow_redirects=False
    )

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://blob.example.test/images/")
    assert response.headers["Cache-Control"] == "public, max-age=60, s-maxage=300"
    assert response.headers["ETag"].startswith('"sha256-')


@pytest.mark.parametrize("withdraw", [False, True])
def test_mirror_and_tombstone_resolution_do_not_depend_on_upstream(
    withdraw: bool,
) -> None:
    client = image_client(
        lookup_failure=ContentFailure.TIMEOUT, ingest=True, withdraw=withdraw
    )

    response = client.get("/image/2026-07-18", follow_redirects=False)

    assert response.status_code == (410 if withdraw else 307)


def test_cli_image_commands_map_safety_and_dependency_outcomes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    pipeline, _, _, _, _ = image_pipeline()
    assert cli.ingest_image(pipeline, 7, b"html", "authorized", json_output=True) == 5
    assert "image_rejected" in capsys.readouterr().out

    pipeline.blob_store.fail = True  # type: ignore[attr-defined]
    assert (
        cli.ingest_image(pipeline, 7, raster_bytes(), "authorized", json_output=True)
        == 4
    )
    assert "image_dependency_failed" in capsys.readouterr().out

    pipeline.repository.fail = True  # type: ignore[attr-defined]
    assert cli.withdraw_image(pipeline, 7, "reason", json_output=True) == 4
    assert "image_dependency_failed" in capsys.readouterr().out


def test_main_dispatches_image_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str, bool]] = []
    monkeypatch.setattr(
        cli,
        "run_image_ingest",
        lambda item, path, note, *, json_output=False: calls.append(
            (item, path, note, json_output)
        )
        or 0,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "daily-miku",
            "image",
            "ingest",
            "7",
            "miku.png",
            "--authorization-note",
            "creator permission",
            "--json",
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 0
    assert calls == [("7", "miku.png", "creator permission", True)]
