"""CLI tests for selection tag initialization."""

import json
from datetime import datetime

import pytest

from daily_miku import cli, main
from daily_miku.config import InitializationSettings
from daily_miku.selection_initialize import (
    InMemorySelectionTagStore,
    SelectionTagInitializer,
    SelectionTagItem,
)

pytestmark = pytest.mark.unit


def test_initialization_settings_do_not_require_database() -> None:
    settings = InitializationSettings.from_environment(
        RAINDROP_TOKEN="token", DATABASE_URL=None, _env_file=None
    )

    assert settings.database_url is None
    assert settings.timezone_name == "Asia/Shanghai"


def test_selection_initialize_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    item = SelectionTagItem(
        7,
        datetime.fromisoformat("2026-07-18T12:00:00+00:00"),
        ("daily-miku", "art"),
    )
    initializer = SelectionTagInitializer(InMemorySelectionTagStore([item]), "UTC")

    assert cli.initialize_selection_tags(initializer, json_output=True) == 0
    document = json.loads(capsys.readouterr().out)

    assert document["status"] == "dry_run"
    assert document["proposed"][0] == {
        "raindrop_id": 7,
        "last_update": "2026-07-18T12:00:00Z",
        "selection_day": "2026-07-18",
        "current_tags": ["daily-miku", "art"],
        "proposed_tag": "daily-miku-2026-07-18",
    }


def test_selection_initialize_failure_json_has_error_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    items = [
        SelectionTagItem(
            7,
            datetime.fromisoformat("2026-07-18T12:00:00+00:00"),
            ("daily-miku",),
        )
    ]
    store = InMemorySelectionTagStore(items, fail_update_ids={7})

    assert (
        cli.initialize_selection_tags(
            SelectionTagInitializer(store, "UTC"), apply=True, json_output=True
        )
        == 4
    )
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "incomplete"
    assert document["error"]["code"] == "initialization_dependency_failed"
    assert document["error"]["details"] == {}


def test_main_dispatches_selection_initialize_apply_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[bool, bool]] = []
    monkeypatch.setattr(
        cli,
        "run_selection_initialize",
        lambda *, apply=False, json_output=False: calls.append((apply, json_output))
        or 0,
    )
    monkeypatch.setattr(
        "sys.argv", ["daily-miku", "selection", "initialize", "--apply", "--json"]
    )

    with pytest.raises(SystemExit) as caught:
        main.main()

    assert caught.value.code == 0
    assert calls == [(True, True)]
