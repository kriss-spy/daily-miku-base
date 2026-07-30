"""Apply the operator-reviewed post-initialization Selection Day corrections."""

from dataclasses import dataclass

from daily_miku.config import InitializationSettings
from daily_miku.raindrop import RaindropSelectionTagStore
from daily_miku.selections import parse_dated_selection_tag


@dataclass(frozen=True)
class Correction:
    """One reviewed move from an initialized date to an empty date."""

    raindrop_id: int
    source: str
    target: str


CORRECTIONS = (
    Correction(1432130116, "2025-11-26", "2025-11-19"),
    Correction(1435409754, "2025-11-26", "2025-11-20"),
    Correction(1441253970, "2025-11-26", "2025-11-21"),
    Correction(1443694669, "2025-11-26", "2025-11-22"),
    Correction(1447741778, "2025-11-26", "2025-11-23"),
    Correction(1449801644, "2025-11-26", "2025-11-24"),
    Correction(1451444053, "2025-11-26", "2025-11-25"),
    Correction(1457593304, "2025-11-30", "2025-11-28"),
    Correction(1461589981, "2025-11-30", "2025-11-29"),
    Correction(1471276169, "2025-12-06", "2025-12-04"),
    Correction(1477460946, "2025-12-07", "2025-12-05"),
    Correction(1480969358, "2025-12-10", "2025-12-09"),
    Correction(1487928364, "2025-12-15", "2025-12-13"),
    Correction(1489118519, "2025-12-15", "2025-12-14"),
    Correction(1495620897, "2025-12-19", "2025-12-17"),
    Correction(1507543146, "2025-12-25", "2025-12-23"),
    Correction(1508808467, "2025-12-25", "2025-12-24"),
    Correction(1532517910, "2026-01-09", "2026-01-08"),
    Correction(1538549805, "2026-01-12", "2026-01-11"),
    Correction(1551678654, "2026-02-05", "2026-02-02"),
    Correction(1565287199, "2026-02-05", "2026-02-03"),
    Correction(1567693026, "2026-02-05", "2026-02-04"),
    Correction(1714497745, "2026-05-15", "2026-05-12"),
    Correction(1716815227, "2026-05-15", "2026-05-13"),
    Correction(1723270625, "2026-05-19", "2026-05-16"),
    Correction(1709973788, "2026-06-06", "2026-05-30"),
    Correction(1732458815, "2026-06-06", "2026-05-31"),
    Correction(1734378245, "2026-06-06", "2026-06-01"),
    Correction(1734708616, "2026-06-06", "2026-06-02"),
    Correction(1734931872, "2026-06-06", "2026-06-03"),
    Correction(1738591312, "2026-06-06", "2026-06-04"),
    Correction(1741963796, "2026-06-06", "2026-06-05"),
    Correction(1744399862, "2026-06-06", "2026-05-27"),
    Correction(1746114184, "2026-06-06", "2026-05-28"),
    Correction(1592341982, "2026-06-08", "2026-06-07"),
    Correction(1602095986, "2026-06-08", "2026-05-25"),
    Correction(1605846727, "2026-06-08", "2026-05-24"),
    Correction(1607831552, "2026-06-08", "2026-05-23"),
    Correction(1621374085, "2026-06-08", "2026-05-22"),
    Correction(1715909857, "2026-06-08", "2026-05-21"),
    Correction(1741645779, "2026-06-08", "2026-05-20"),
    Correction(1744915288, "2026-06-08", "2026-05-11"),
    Correction(1747455434, "2026-06-08", "2026-05-10"),
    Correction(1749820481, "2026-06-09", "2026-05-09"),
    Correction(1771486773, "2026-06-24", "2026-06-22"),
    Correction(1761400816, "2026-07-14", "2026-07-12"),
    Correction(1761679463, "2026-07-14", "2026-07-16"),
    Correction(1789947412, "2026-07-14", "2026-07-18"),
    Correction(1791447302, "2026-07-17", "2026-07-19"),
)


def main() -> None:
    """Apply and verify every reviewed correction, stopping on drift."""
    settings = InitializationSettings.from_environment()
    store = RaindropSelectionTagStore(settings.raindrop_token.get_secret_value())
    applied = 0
    skipped = 0

    for correction in CORRECTIONS:
        item = store.get(correction.raindrop_id)
        dated_tags = tuple(
            tag for tag in item.tags if parse_dated_selection_tag(tag) is not None
        )
        target_tag = f"daily-miku-{correction.target}"
        if dated_tags == (target_tag,):
            skipped += 1
            continue
        source_tag = f"daily-miku-{correction.source}"
        if dated_tags != (source_tag,):
            raise RuntimeError(
                f"Raindrop {correction.raindrop_id} drifted: {dated_tags!r}"
            )
        desired = tuple(tag for tag in item.tags if tag != source_tag) + (target_tag,)
        store.update_tags(correction.raindrop_id, desired)
        verified = store.get(correction.raindrop_id)
        verified_dated = tuple(
            tag for tag in verified.tags if parse_dated_selection_tag(tag) is not None
        )
        if verified_dated != (target_tag,):
            raise RuntimeError(
                f"Raindrop {correction.raindrop_id} did not retain {target_tag}"
            )
        applied += 1
        print(f"{correction.raindrop_id}: {correction.source} -> {correction.target}")

    print(f"Applied {applied}; already correct {skipped}; total {len(CORRECTIONS)}")


if __name__ == "__main__":
    main()
