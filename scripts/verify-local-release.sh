#!/usr/bin/env bash
set -euo pipefail

uv run --python 3.13 --extra dev python -m pytest
uv run --python 3.13 --extra dev ruff check \
  src/daily_miku/catalog.py \
  src/daily_miku/config.py \
  src/daily_miku/content_source.py \
  src/daily_miku/asgi.py \
  src/daily_miku/delivery.py \
  src/daily_miku/doctor.py \
  src/daily_miku/domain \
  src/daily_miku/http \
  src/daily_miku/images \
  src/daily_miku/ledger \
  src/daily_miku/logging_config.py \
  src/daily_miku/main.py \
  src/daily_miku/migration_baseline.py \
  src/daily_miku/reliability.py \
  src/daily_miku/selections.py \
  src/daily_miku/services.py \
  tests/test_v2_*.py
uv run --python 3.13 --extra dev ruff check --select=PYI .
uv build

python - <<'PY'
from pathlib import Path
from zipfile import ZipFile

wheel = max(Path("dist").glob("*.whl"), key=lambda path: path.stat().st_mtime)
with ZipFile(wheel) as archive:
    names = set(archive.namelist())
required = {
    "daily_miku/static/editorial.css",
    "daily_miku/templates_v2/slot.html",
    "daily_miku/templates_v2/archive.html",
    "daily_miku/templates_v2/search.html",
    "daily_miku/ledger/migrations/0004_email_deliveries.sql",
    "daily_miku/ledger/migrations/0005_remove_selection_ledger.sql",
}
missing = sorted(required - names)
if missing:
    raise SystemExit(f"release wheel is missing: {missing}")
print(wheel)
PY
