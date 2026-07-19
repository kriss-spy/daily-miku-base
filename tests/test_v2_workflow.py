"""Tests for the disabled v2 reconciliation schedule."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_reconciliation_workflow_is_gated_and_supports_manual_runs() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github/workflows/reconcile-v2.yml"
    ).read_text(encoding="utf-8")

    assert 'cron: "*/15 * * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "vars.ENABLE_V2_RECONCILIATION == 'true'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "curl --fail-with-body" in workflow
    assert "Authorization: Bearer ${RECONCILE_SECRET}" in workflow
    assert '"${RECONCILE_URL}/internal/reconcile"' in workflow
