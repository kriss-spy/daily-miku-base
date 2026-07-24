"""Deterministic protected migration baseline artifacts."""

import json
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .content_source import TaggedItem
from .initialize import InitializationReport

IMAGE_CLASSIFICATIONS = {
    "validated_controlled_mirror",
    "intentional_no_image",
    "confirmed_withdrawal",
    "accepted_failure",
}


@dataclass(frozen=True)
class BaselineArtifact:
    """Canonical manifest bytes plus unresolved operator gates."""

    document: dict[str, object]
    unresolved: tuple[str, ...]

    @property
    def canonical_bytes(self) -> bytes:
        return (
            json.dumps(self.document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()

    @property
    def checksum(self) -> str:
        return sha256(self.canonical_bytes).hexdigest()

    def write_immutable(self, path: Path) -> tuple[Path, Path]:
        """Create a private manifest and checksum without replacing evidence."""
        checksum_path = path.with_suffix(path.suffix + ".sha256")
        if path.exists() or checksum_path.exists():
            raise FileExistsError("migration baseline artifacts are immutable")
        path.write_bytes(self.canonical_bytes)
        os.chmod(path, 0o600)
        checksum_path.write_text(f"{self.checksum}  {path.name}\n", encoding="ascii")
        os.chmod(checksum_path, 0o600)
        return path, checksum_path


def build_baseline(
    items: tuple[TaggedItem, ...],
    initialization: InitializationReport,
    evidence: dict[str, object],
) -> BaselineArtifact:
    """Combine complete export facts with explicit human-reviewed evidence."""
    rows = {row.raindrop_id: row for row in initialization.proposed_rows}
    images = _mapping(evidence.get("images"))
    conflict_decisions = _mapping(evidence.get("conflicts"))
    duplicate_decisions = _mapping(evidence.get("duplicates"))
    routes = _mapping(evidence.get("v1_routes"))
    unresolved: list[str] = []
    exported = []
    for item in sorted(items, key=lambda value: value.raindrop_id):
        row = rows.get(item.raindrop_id)
        classification = images.get(str(item.raindrop_id))
        if classification not in IMAGE_CLASSIFICATIONS:
            unresolved.append(f"image:{item.raindrop_id}")
        exported.append(
            {
                "raindrop_id": item.raindrop_id,
                "legacy_date_evidence": (
                    row.last_update.isoformat() if row is not None else None
                ),
                "derived_selection_day": (
                    row.selection_day.value.isoformat() if row is not None else None
                ),
                "derivation": "last_update interpreted in configured calendar timezone",
                "source_url": item.source_url,
                "cover_identity": item.cover_identity,
                "tags": list(item.tags),
                "image_classification": classification,
            }
        )
    for conflict in initialization.conflicts:
        key = conflict.selection_day.value.isoformat()
        if key not in conflict_decisions:
            unresolved.append(f"conflict:{key}")
    for duplicate in initialization.duplicate_identities:
        key = f"{duplicate.kind}:{duplicate.identity}"
        if key not in duplicate_decisions:
            unresolved.append(f"duplicate:{key}")
    for route, outcome in routes.items():
        if (
            not isinstance(outcome, dict)
            or "selected_id" not in outcome
            or "status" not in outcome
        ):
            unresolved.append(f"v1_route:{route}")
    document: dict[str, object] = {
        "format": "daily-miku-migration-baseline-v1",
        "timezone": evidence.get("timezone", "Asia/Shanghai"),
        "export": exported,
        "initialization": initialization.as_dict(),
        "v1_routes": routes,
        "decisions": {
            "conflicts": conflict_decisions,
            "duplicates": duplicate_decisions,
        },
        "unresolved": sorted(unresolved),
        "review_complete": not unresolved,
    }
    return BaselineArtifact(document, tuple(sorted(unresolved)))


def compare_retained_routes(
    expected: dict[str, int | None], actual: dict[str, int | None]
) -> tuple[str, ...]:
    """Return every retained date whose approved selected identity changed."""
    dates = sorted(set(expected) | set(actual))
    return tuple(day for day in dates if expected.get(day) != actual.get(day))


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}
