# Daily Miku v1 Compatibility Inventory

Evidence for [Establish the v1 behavioral baseline](https://github.com/kriss-spy/daily-miku-base/issues/5), recorded 2026-07-17. This inventory describes v1; it does not design v2.

## Effective Production Surface

`vercel.json` routes every production request to `api/hybrid.py`. The larger FastAPI application used by `daily-miku serve` is not the deployed contract.

| Interface | Observed production behavior | Compatibility conclusion |
| --- | --- | --- |
| `/`, `/today` | Render today's HTML; `/today` returns HTML rather than redirecting. | Preserve today's web view and alias. |
| `/{YYYY-MM-DD}` | Renders a dated page; missing data is a 200 empty/error page. | Preserve dated access, not the incorrect missing status. |
| `/list` | Renders up to 20 recently updated bookmarks. | Preserve recent browsing, not exact limit/order. |
| `/health` | Returns `200 {"status":"healthy"}` without dependency checks. | Preserve process liveness only. |
| `/api/today` | Returns one formatted record, or an error object with status 200. | Preserve purpose and successful fields, not error-as-success. |
| `/api/list` | Returns up to 10 records, or an error object instead of an array. | Preserve list purpose, not its union-shaped failure response. |
| `/image/{date}` | Proxies cover bytes, trusts upstream type, caches 24 hours; returns 404 when absent and 502 on request failure. | Preserve the dated direct-image URL, not unsafe proxy details. |

Evidence: `vercel.json:1-5`, `api/hybrid.py:41-124`, `api/hybrid.py:143-244`, `api/hybrid.py:247-309`, and `api/hybrid.py:312-435`.

Successful `/api/today` and `/api/list` records contain `date`, `title`, `cover`, `link`, `excerpt`, `domain`, `tags`, `raindropId`, and `timestamp`; `timestamp` is the bookmark's `created` value even though `date` comes from `lastUpdate` (`api/hybrid.py:63-92`).

## Selection Behavior

Production and local date lookup search only page zero of at most 50 tagged bookmarks, sort by undocumented `-lastUpdate`, convert `lastUpdate` to fixed UTC+8, and silently return the first item on the requested day (`api/hybrid.py:98-124`; `src/daily_miku/raindrop.py:93-188`).

This explains [the date-shift bug](https://github.com/kriss-spy/daily-miku-base/issues/2): any later edit changes `lastUpdate`, removes the item from its former date, and may make it today's item. Other routes derive dates from `created`, so v1 has no consistent date meaning (`src/daily_miku/server.py:168-186`, `210-228`, `252-283`, `363-383`).

Preserve the `Asia/Shanghai` calendar convention. Do not preserve `lastUpdate` as the true Selection Day, first-match conflict suppression, mixed date meanings, or the 50-item archive ceiling. The one-time v2 initializer may import current `lastUpdate` dates only as explicitly legacy mappings needed to retain existing URLs.

## Local-Only Surface

The local FastAPI app additionally exposes root API metadata, latest, random, stats, image, week, month, and year JSON routes plus local HTML variants (`src/daily_miku/server.py:102-549`). These are not production compatibility requirements because Vercel never routes to that app. Some are misleading: random samples only 50 items, stats total at most 50, and year groups UTC `created` values.

Templates and navigation are also inconsistent: local image pages link to JSON routes, and `home.html` is unused (`src/daily_miku/templates/image.html:57-80`). Do not preserve these defects or dormant pages.

## CLI And Email

The installed `daily-miku` CLI provides `fetch-today`, `fetch-date`, `test-connection`, `list`, `send-email`, and `serve` (`pyproject.toml:19-20`; `src/daily_miku/main.py:8-49`; `src/daily_miku/cli.py:12-150`). Preserve the first five command purposes. `serve` is development convenience, not a public compatibility promise. Do not preserve uncaught argument/config errors, mixed displayed dates, token-prefix output, or dependency failures disguised as empty results.

`fetch-today` and `fetch-date DATE` print formatted JSON and exit 1 when no item is found. `test-connection` prints connectivity, token-prefix, tag, and sample information. `list [n]` defaults to ten and prints creation dates despite modification ordering; a non-integer limit raises an uncaught `ValueError`. Missing `RAINDROP_TOKEN` raises during client construction, while request failures usually collapse into the same empty result used for no bookmarks.

`send-email` finds today's item, builds HTML, downloads a cover for a CID attachment, and sends through authenticated STARTTLS SMTP to one configured recipient (`src/daily_miku/email.py:38-196`). Preserve scheduled HTML email, source attribution, and image-focused intent. Image-fetch failure is currently swallowed while HTML still references the missing CID; this can report success with a broken image and must not be preserved.

When no item is found, the command exits 1, records a per-day local failure count, and attempts a warning email from the second failure. SMTP failure also exits 1. Image attachment failure alone remains nonfatal and the SMTP send may still report success.

The GitHub Action runs daily at 04:00 UTC and manually (`.github/workflows/daily-email.yml:1-47`). Its local failure counter cannot reliably survive ephemeral runners, and its final step always prints success. Neither behavior is a stable capability.

## Image Failure Baseline

The deployed page embeds Raindrop's cover directly while `/image/{date}` downloads it without validation or source-specific handling (`api/hybrid.py:227-234`, `380-417`). [The Pixiv failure](https://github.com/kriss-spy/daily-miku-base/issues/1) disproves documentation claiming Raindrop covers should always work. A successful HTML/error upstream response may also be forwarded as if it were an image.

Preserve dated image delivery when a valid image exists. Do not claim universal Pixiv/X support, preserve broken CID fallback, or treat current caching and content-type behavior as contracts.

## Configuration And Deployment

Observed configuration includes `RAINDROP_TOKEN`, `RAINDROP_TAG`, `RAINDROP_CACHE_TTL`, SMTP settings, `EMAIL_FROM`, `EMAIL_TO`, and `LOG_LEVEL`. The effective production platform is Vercel. Netlify instructions, Python 3.10 workflows conflicting with the package's Python 3.11 minimum, divergent dependency files, and module-import configuration parsing are defects rather than capabilities.

Evidence: `.env.example`, `pyproject.toml:6-20`, `requirements.txt`, `.github/workflows/ci.yml:16-31`, `.github/workflows/daily-email.yml:16-30`, and `docs/deployment.md`.

## Tests And Confidence

Tests cover the local Raindrop client, local FastAPI app, and email helpers, but not the deployed `api/hybrid.py` handler. There are no regressions for later edits changing a date, timezone boundaries, duplicate candidates, pagination beyond 50, Pixiv/non-image responses, CLI behavior, or image attachment success (`tests/test_raindrop.py`, `tests/test_api.py`, `tests/test_email.py`).

The defensible v1 baseline is therefore the small deployed route set, established CLI command purposes, and daily email workflow. Documentation and local-only handlers are supporting evidence, not production contracts.
