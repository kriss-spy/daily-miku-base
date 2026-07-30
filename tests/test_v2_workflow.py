"""Tests for removal of the obsolete reconciliation schedule."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_reconciliation_workflow_and_health_probe_are_removed() -> None:
    root = Path(__file__).parents[1]
    health = (root / ".github/workflows/operational-health.yml").read_text(
        encoding="utf-8"
    )

    assert not (root / ".github/workflows/reconcile-v2.yml").exists()
    assert "/internal/reconciliation-status" not in health
