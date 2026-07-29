"""Adapter tests for Raindrop selection tag initialization operations."""

from typing import Any

import pytest

from daily_miku.raindrop import RaindropSelectionTagStore

pytestmark = pytest.mark.unit


class Response:
    """Minimal successful requests response fake."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        """Represent a successful response."""

    def json(self) -> dict[str, Any]:
        """Return configured JSON."""
        return self.payload


def raw_item(identity: int, tags: list[str]) -> dict[str, Any]:
    """Build one API item with initialization fields."""
    return {
        "_id": identity,
        "lastUpdate": "2026-07-18T12:00:00Z",
        "tags": tags,
    }


def test_adapter_paginates_and_retains_prefix_matches_for_diagnostics() -> None:
    calls: list[dict[str, Any]] = []
    first = [raw_item(value, ["daily-miku"]) for value in range(1, 50)]
    first.append(raw_item(50, ["daily-miku-prefix"]))
    second = [raw_item(51, ["daily-miku"])]

    def get(_url: str, **kwargs: Any) -> Response:
        calls.append(kwargs)
        return Response({"items": first if len(calls) == 1 else second, "count": 51})

    store = RaindropSelectionTagStore("token", get=get)

    items = store.scan_generic()

    assert len(items) == 51
    assert 50 in {item.raindrop_id for item in items}
    assert [call["params"]["page"] for call in calls] == [0, 1]
    assert "search" not in calls[0]["params"]


def test_adapter_uses_single_raindrop_put_with_tags_only() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def put(url: str, **kwargs: Any) -> Response:
        calls.append((url, kwargs))
        return Response({"result": True})

    store = RaindropSelectionTagStore("token", put=put)
    store.update_tags(42, ("art", "daily-miku-2026-07-18"))

    assert calls[0][0].endswith("/raindrop/42")
    assert calls[0][1]["json"] == {"tags": ["art", "daily-miku-2026-07-18"]}


def test_adapter_rejects_repeated_page_identity() -> None:
    first = [raw_item(value, ["daily-miku"]) for value in range(1, 51)]
    second = [raw_item(50, ["daily-miku"])]
    calls = 0

    def get(_url: str, **_kwargs: Any) -> Response:
        nonlocal calls
        calls += 1
        return Response({"items": first if calls == 1 else second, "count": 51})

    with pytest.raises(Exception, match="complete selection-tag snapshot"):
        RaindropSelectionTagStore("token", get=get).scan_generic()


def test_adapter_rejects_unconfirmed_update() -> None:
    store = RaindropSelectionTagStore(
        "token", put=lambda *_args, **_kwargs: Response({"result": False})
    )

    with pytest.raises(Exception, match="could not update selection tags"):
        store.update_tags(42, ("daily-miku-2026-07-18",))
