"""Checks that preview verification cannot masquerade as completed evidence."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_preview_record_template_is_pending_and_does_not_authorize_cutover() -> None:
    document = Path("docs/protected-preview-verification.md").read_text()

    assert "status: pending" in document
    assert "cutover_scheduling_approved: false" in document
    assert "not evidence" in document
    assert "never routes public traffic" in document


def test_local_release_gate_checks_required_packaged_assets() -> None:
    script = Path("scripts/verify-local-release.sh").read_text()

    assert "python -m pytest" in script
    assert "ruff check --select=PYI" in script
    assert "uv build" in script
    assert "0004_email_deliveries.sql" in script
    assert "templates_v2/archive.html" in script
