# Daily Miku v2 Application Architecture

Decision for [Design the v2 application architecture](https://github.com/kriss-spy/daily-miku-base/issues/9), confirmed 2026-07-18.

## Principles

- One Python application. FastAPI server-renders all pages; progressive JavaScript enhances them. There is no separate frontend.
- A small number of deep modules hide each capability behind a small interface. Delivery mechanisms (HTTP, CLI) are thin adapters with no domain logic.
- Dependency direction is fixed: delivery → deep modules → domain core. The domain core imports nothing outside itself.
- Slot resolution is read-only. Selection writes happen in Raindrop by adding, removing, or replacing a Dated Selection Tag.
- Module code is synchronous everywhere. One code path serves web, CLI, and email automation.
- External systems — Postgres, Raindrop, Vercel Blob, SMTP — sit behind internal seams with in-memory fakes. Tests never touch the network.
- Deployment concerns live at the edge (`vercel.json`, `api/`, `public/`), never inside the package.

## Application Shape

A single FastAPI application renders the HTML routes from the [HTTP contract](http-contract.md), serves the JSON API, and resolves direct images. The same package provides the CLI and the email automation from the [CLI and email contract](cli-email-contract.md). All three surfaces share domain semantics in-process through the deep modules below; nothing reimplements selection rules.

## Module Map

Four deep modules sit over a pure domain core.

### Domain Core

Pure, I/O-free Python. Defines Dated Selection Tag parsing, the Daily Slot and its `empty`, `selected`, and `conflict` states, future-date rules, invalid multi-date assignments, and a `Clock` protocol so tests control "today". Every date decision in the system flows through this module.

### Slot Catalog

The single read model for Daily Slots. Its interface is the contract's read surface: `get_slot`, `today`, `latest`, `random`, `range`, `archive`, `search`, and `statistics`. Its implementation hides complete Raindrop discovery, strict tag parsing, request-local indexing, state derivation, and conflict rules. HTML pages, JSON endpoints, CLI read commands, and email preconditions all consume exactly this module.

### Selection Tag Catalog

Discovers bookmarks carrying the `daily-miku-` prefix, parses canonical dated tags, and returns an in-memory date index plus malformed and multi-date diagnostics. It never persists Selection Days. A complete scan is authoritative for that operation; bounded in-memory caching may reduce repeated Raindrop calls but must expire and may be discarded without data loss.

### Image Pipeline

`resolve_image(date)` implements the mirror-first strategy from [Resilient Image Delivery](../research/image-delivery.md) and returns the contract's distinct outcomes (redirect target, no image, conflict refusal, withdrawal, upstream failure classes). `ingest()` and `withdraw()` provide the controlled operator mutations. The module hides source adapters, validation and normalization, provenance and tombstone storage, content-addressed naming, and the Blob store.

### Email Delivery

`send(date, force)` implements the contract's ordered preconditions, per-recipient reservation and idempotency, bounded retries, and durable outcome records. Returns the delivery report the CLI renders; never prints or exposes recipient addresses beyond configuration.

## Dependency Direction And Import Rules

- `http/` and `cli/` import the deep modules and composition root; they contain parsing, rendering, and exit-code mapping only.
- The deep modules import the domain core and the ports of the adapters they compose; they never import `http/`, `cli/`, or concrete adapters.
- Concrete adapters (Postgres, Raindrop API, Blob, SMTP) are imported only by the composition root and by tests.
- The domain core imports nothing outside itself.

## Selection Discovery And Read Purity

Slot Catalog reads never write. Each uncached operation obtains a complete Raindrop view of Dated Selection Tags and current bookmark content. The service may keep a short-lived in-memory result, but it has no durable reconciliation process and no correctness dependency on a scheduler. Operator validation uses the same complete scan and reports malformed tags, multi-date assignments, Slot conflicts, and likely duplicate identities.

## Data Access

- psycopg v3 with hand-written SQL. No ORM: image records and the Email Delivery store form a small explicit operational schema, and hand-written SQL keeps the module interfaces small. No table stores or indexes Selection Days.
- Schema changes ship as numbered `.sql` migration files applied transactionally, recorded in a `schema_migrations` table. `doctor` compares that table against the application's expected schema version.
- On Vercel, adapters open per-invocation connections against the provider's pooled endpoint (Neon by default). Local development uses a small lazy pool. Pooling strategy is hidden inside the adapters.

## Synchronous Execution Model

All module and adapter code is synchronous. FastAPI handlers are plain `def` functions, so Starlette runs them in its threadpool. The CLI and email job call the same synchronous modules directly, with no `asyncio` wrappers and no dual-mode adapters. The application's latency is dominated by upstream calls and its traffic is low; async concurrency would add a second mode to every seam for no measurable benefit.

## Composition And Settings

One `Settings` class (pydantic-settings) parses the contract's configuration namespace; nothing else reads environment variables. One composition root, `build_services(settings)`, constructs the adapter graph and injects it into the deep modules. The FastAPI app factory calls it at startup and serves the graph through request dependencies; the CLI calls the same factory per invocation. No module constructs its own dependencies. Configuration errors fail web startup and exit CLI commands with code `3`.

## HTTP Delivery Layer

Routers are thin: parse and validate input, call a deep module, render or serialize the result, and map domain outcomes to the contract's status codes and error envelope. A middleware assigns each request a `request_id`, included in every error envelope and structured log line. HTML rendering uses Jinja2 templates; progressive-enhancement scripts and stylesheets are static assets.

## CLI Delivery Layer

Commands mirror the contract surface (`slot`, `archive`, `doctor`, `email`, `selection`, and `image`). Each command builds services through the composition root, calls the matching deep module, renders human output or the contract's JSON document, and maps results onto the contract's exit codes.

## Frontend Assets And Progressive Enhancement

Server-rendered pages are enhanced by small vanilla ES-module scripts served from `public/`. There is no Node toolchain in CI or deployment. Dynamic interactions consume the JSON API already defined by the HTTP contract, so enhancement adds no new server surface. The core-browsing prototype may present evidence that amends this decision (for example, adopting htmx); a build-step frontend remains ruled out by the application shape.

## Package Layout

```text
src/daily_miku/
  domain/            # pure core: dated tags, slots, future-date rules, Clock
  raindrop/          # selection/content source: port, client.py adapter, memory.py fake
  catalog.py         # Slot Catalog
  selections.py      # Selection Tag Catalog and validation
  images/            # Image Pipeline: resolve, sources, validate, blob store
  emailer/           # Email Delivery: send, smtp adapter, Postgres delivery store
  storage/           # operational SQL migrations and Postgres adapters
  http/              # app factory, routes/, templates/, error envelope
  cli/               # command surface
  config.py          # Settings
  services.py        # build_services composition root
public/              # static assets served by Vercel's CDN
api/index.py         # ASGI entrypoint re-exporting the app
vercel.json          # application rewrites
.github/workflows/   # email and operational health schedules
```

`api/` and `public/` are deployment edges, not package code.

## Vercel Deployment

- One ASGI entrypoint: `api/index.py` re-exports the FastAPI app; `vercel.json` rewrites every route to it. Vercel's Python runtime serves ASGI directly; no Mangum or Lambda adapter is used.
- Selection dates require no scheduler or internal mutation endpoint; Raindrop tags are read directly.
- Static assets ship in `public/` and are served by Vercel's CDN without invoking the function.
- If a route later proves to need distinct resources, promoting one router to its own function is a `vercel.json` change, not a refactor, because routers are thin adapters.
- Local development runs the same app (`daily-miku serve` or `uvicorn`) against local or preview dependencies.

## Testing Seams

- The interface is the test surface: deep modules are tested through their public interfaces with in-memory fakes for the Raindrop, operational store, Blob, and SMTP seams.
- HTTP behavior is tested through the FastAPI app with `TestClient`; CLI behavior through command invocation, both against fakes.
- The `Clock` seam makes future-date behavior deterministic in tests; strict tag parsing is timezone-independent.
- Contract fixtures (slot representations, error envelopes, exit codes) guard the HTTP and CLI contracts against drift.

## Rejected Alternatives

- **Separate frontend (SPA or framework islands)**: the resolved contracts and pending prototype require nothing a server-rendered app cannot provide; a second deployable only adds surface.
- **By-kind layering (routers/models/services/clients)**: spreads Daily Slot semantics across layers; capability modules give the locality a single maintainer needs.
- **Selection Ledger and scheduled reconciliation**: duplicate date state already encoded by the operator, introduce synchronization lag, and create a second source of truth.
- **SQLAlchemy/SQLModel with Alembic**: more concepts than the small operational schema justifies; numbered SQL files and a version table cover migration and `doctor` needs.
- **Async throughout**: dual-mode seams with no benefit at this traffic profile.
- **Per-concern serverless functions and Mangum**: more cold starts and wiring for unproven resource needs; Mangum adapts to an interface Vercel does not use.
- **htmx or a Node build step committed now**: no build step keeps deployment Python-only; library adoption awaits prototype evidence.
