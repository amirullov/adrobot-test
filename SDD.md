# Adrobot Keitaro Wrapper — Software Design Document

Status: implementation baseline for the take-home assignment
Date: 2026-11-19

## 1. Goal and scope

The service removes two repetitive Keitaro tasks: create a correctly wired campaign and safely edit the offers of its offer stream. It is a deliberately small monolith: FastAPI serves JSON endpoints and server-rendered pages, SQLAlchemy persists local state, Alembic owns the schema, and one `KeitaroClient` adapter owns all tracker calls.

In scope:

- campaign creation from a name, ISO 3166-1 alpha-2 country code and Keitaro offer ID;
- fixed domain, campaign group and traffic source from configuration;
- one country-filtered Google redirect stream and one fallback offer stream;
- offer search/selection, validation, operation result and actionable errors;
- loading an existing campaign's current streams and offers;
- a durable local draft with add, remove, bring back and cancel;
- one guarded push of the final active offer list;
- deterministic integer shares that total exactly 100%;
- external-change detection, request timeouts, bounded safe retries and idempotency;
- a fake Keitaro implementation for a complete local demo and tests.

Out of scope: authentication/roles, multi-tenant isolation, report dashboards, background jobs, auto-reconciliation, campaign/stream deletion rollback, Kubernetes, Redis, Celery/RabbitMQ and a separate SPA toolchain. These do not solve a demonstrated MVP problem. If the wrapper became multi-user, authentication and a proper ownership model would be the first additions.

## 2. Evidence, assumptions and open questions

Verified in the official Keitaro Admin API reference:

- authentication uses `Api-Key` (Bearer is also supported);
- campaigns are `GET/POST /admin_api/v1/campaigns`, and a campaign can carry `domain_id`, `group_id` and `traffic_source_id`;
- campaign streams are read through `GET /admin_api/v1/campaigns/{id}/streams`;
- offers are read through `GET /admin_api/v1/offers`;
- a stream is partially updated through `PUT /admin_api/v1/streams/{id}` and its schema contains `filters`, `offers`, `action_type`, `action_payload`, `state` and `updated_at`;
- campaign creation requires at least `alias` and `name`.

The public reference documents shapes but does not fully specify the accepted payload semantics for every Keitaro version. The following are isolated compatibility assumptions, not facts hidden in business code:

- stream creation uses `POST /campaigns/{campaign_id}/streams`;
- the country filter is `{name: "country", mode: "accept", payload: ["US"]}`;
- an external redirect stream uses `action_type: "http"` and string `action_payload`;
- an offer stream uses `action_type: "offer"` and an `offers` array.

Before real deployment, capture the successful payload from the target tracker's built-in Swagger or browser Network panel, then adjust only `KeitaroPayloadBuilder`. Keitaro itself recommends inspecting its Admin UI requests when parameters vary by version. The fake mode never pretends to prove compatibility with a real tracker.

The supplied video confirms the editor behavior: dirty rows are highlighted; removed offers remain visible, receive 0%, and show Bring Back; 3 active offers display 34/33/33; 4 display 25 each; 5 display 20 each.

Open questions for the real environment:

- exact Keitaro version/edition and whether Admin API is enabled;
- confirmed country-filter and redirect action payloads for that version;
- IDs for domain, campaign group and traffic source;
- expected campaign alias convention and Google URL;
- whether a compensating archive is desired if campaign creation succeeds but a stream creation fails.

## 3. User scenarios

### Create campaign

1. The page loads searchable active offers from Keitaro.
2. The user enters campaign name and a two-letter country code, and selects an offer.
3. The API validates locally and verifies the offer exists.
4. With one idempotency key it creates the campaign, then Google stream, then offer stream.
5. It stores the resulting IDs and a normalized snapshot, then returns links and status.
6. Validation errors are field-specific. Keitaro authentication, timeout, rejection and partial-creation errors are distinguishable; secrets and raw sensitive payloads are not logged.

### Edit existing campaign

1. The user opens a local campaign or imports a Keitaro campaign ID.
2. Fetch Streams obtains the latest campaign streams and offers. The Google stream is shown as protected and never edited.
3. The offer stream is selected by the stored ID. When importing, the service selects the single stream containing offers; zero or multiple candidates are a clear error requiring configuration.
4. Add/remove/bring-back mutate only the persisted draft. Removed rows remain visible with share 0.
5. Cancel discards the draft and restores the server snapshot.
6. Push re-fetches the remote stream, compares its fingerprint with the base snapshot, and rejects with 409 if it changed externally.
7. If unchanged, one `PUT /streams/{id}` sends the complete final `offers` array. On failure the draft remains. On success the returned/confirmed state becomes the new snapshot and the draft clears.

## 4. Architecture and justified choices

```text
Browser (Jinja HTML + app.js)
          |
          v
FastAPI routes ---- Pydantic contracts
          |
          v
CampaignService ---- SQLAlchemy transaction ---- PostgreSQL
          |
          v
KeitaroClient interface
    |                |
HttpKeitaroClient   FakeKeitaroClient
    |
Keitaro Admin API
```

Why server-rendered HTML plus vanilla JavaScript: the UI has two pages and a small state machine, so React would add a build, dependency and deployment surface without reducing risk. The REST API remains usable by a future SPA. HTMX was also considered, but plain `fetch` keeps draft transitions explicit and testable.

Why a synchronous SQLAlchemy session: Keitaro network latency dominates and the MVP has low concurrency. FastAPI runs ordinary `def` handlers in its threadpool. This is easier to explain and operate than mixing async DB and HTTP concerns. A later high-throughput service can move both boundaries to async together.

Why persisted JSON snapshots/drafts: the aggregate is a small ordered offer list updated atomically. Normalizing every draft row would add joins and transition bookkeeping without a query requirement. Campaign identity, version and sync metadata remain typed columns.

Why no queue or distributed lock: Push is user-driven and should return an immediate result. A database row lock plus `syncing` flag and draft version prevents same-service double submission. Multi-replica recovery can later add a lease timestamp; it is not needed for the Compose MVP.

## 5. Modules

- `app/main.py`: app factory, exception mapping, static/templates.
- `app/config.py`: environment-backed configuration; secrets excluded from repr/logging.
- `app/db.py`, `app/models.py`: engine/session and persisted aggregates.
- `app/schemas.py`: HTTP request/response contracts.
- `app/api.py`: thin HTTP routes; no Keitaro payload logic.
- `app/services.py`: use cases, transactions, fingerprints and invariants.
- `app/keitaro/base.py`: domain types, errors and client protocol.
- `app/keitaro/http.py`: authenticated HTTP transport, timeout/retry policy.
- `app/keitaro/payloads.py`: version-sensitive payload construction.
- `app/keitaro/fake.py`: deterministic in-process tracker.
- `app/templates`, `app/static`: progressively enhanced UI.

## 6. Data model and migration

`campaigns`:

- local integer `id`;
- unique `keitaro_campaign_id`;
- `name`, `country_code`, `google_stream_id`, `offer_stream_id`;
- `server_snapshot` JSON: normalized ordered rows `{offer_id, name, state, share}`;
- nullable `draft` JSON with the same rows, including locally removed rows;
- `remote_fingerprint` SHA-256 of editable remote fields;
- optional `remote_updated_at` diagnostic value;
- monotonic `draft_version` sent in mutation bodies or the remove query parameter;
- `syncing`, `last_error`, timestamps.

`idempotency_records`:

- unique key, operation name, SHA-256 request hash;
- status (`in_progress`, `succeeded`, `failed_safe`, `rejected`, `outcome_unknown`), response JSON and timestamps.

Migration `0001_initial` creates both tables and constraints. Alembic reads the same `DATABASE_URL` as the app; application startup never silently calls `create_all`.

## 7. REST contracts

- `GET /api/health` → process status and configured Keitaro mode, never secrets.
- `GET /api/offers?q=` → `[{id,name,state}]`.
- `POST /api/campaigns` with `{name,country_code,offer_id}` and required `Idempotency-Key` → 201 campaign view; replay returns the stored result; same key/different body → 409.
- `GET /api/campaigns` → locally known campaigns.
- `POST /api/campaigns/import` with `{keitaro_campaign_id}` → local campaign aggregate.
- `POST /api/campaigns/{id}/fetch` → replaces clean snapshot; if dirty, returns 409 rather than destroying draft.
- `GET /api/campaigns/{id}` → snapshot, effective rows, `dirty`, `syncing`, `draft_version`, links.
- `POST /api/campaigns/{id}/draft/offers` with `{offer_id,version}` → updated draft.
- `DELETE /api/campaigns/{id}/draft/offers/{offer_id}?version=N` → marks removed, does not delete the row.
- `POST /api/campaigns/{id}/draft/offers/{offer_id}/bring-back` with `{version}`.
- `POST /api/campaigns/{id}/draft/cancel` with `{version}`.
- `POST /api/campaigns/{id}/push` with `{version}` → saved state; 409 for stale local version, concurrent push or changed remote fingerprint.

Errors use `{error:{code,message,details?,retryable}}`. Keitaro status/body is sanitized and mapped to stable codes.

## 8. Frontend state

- `serverSnapshot`: last remote state confirmed by Fetch or successful Push.
- `draft`: persisted working copy; created on first edit.
- `dirty`: normalized draft differs from snapshot.
- `syncing`: server accepted a Push and holds the per-campaign guard.
- `draftVersion`: optimistic concurrency token included in every mutation.

The UI does not optimistically claim a remote save. Buttons are disabled while their own request is in flight; the backend is authoritative. A failed Push shows an error and re-renders the unchanged draft.

Stats and Trends are intentionally `—`: the assignment and verified endpoints do not define a time window, metrics or report contract. Invented numbers would be misleading. The columns remain so a future reporting endpoint can fill them.

## 9. Share algorithm

For `n > 0`, compute `base = 100 // n`, `remainder = 100 % n`. Preserve row order and give the first `remainder` active offers `base + 1`, all others `base`. Removed rows get 0.

- 0 active offers: invalid draft for Push; UI shows 0 and a clear error. Keitaro is never updated to an empty offer stream.
- 1 active offer: 100%.
- 3: 34/33/33; 4: 25/25/25/25; 5: 20 each.

This is deterministic, integer-only and always totals exactly 100.

## 10. Reliability, retries and idempotency

HTTP connect/read/write/pool timeouts are explicit. GET requests retry at most twice for network errors, timeouts, 408, 429 and selected 5xx responses with short exponential backoff plus jitter. Mutating POST/PUT requests are never automatically retried because the Admin API documentation does not promise idempotency. A mutating network failure, malformed success response, 408 or 5xx has `outcome_unknown=true`, so callers are not encouraged to repeat an operation that may already have applied.

Campaign creation requires an application idempotency key. Claiming a new key is protected by the database unique constraint; an insert race is rolled back and the winning record is reloaded. A completed local record is replayed. A failure during the read-only offer preflight is `failed_safe` and may retry with the same key. A crash or ambiguous response after a mutating call is recorded as `outcome_unknown` and reported as `creation_outcome_unknown` or `creation_partially_failed`; an operator must inspect Keitaro before using a new key. The service does not create duplicates to hide uncertainty.

Fake Keitaro is deliberately in-process and resets on every process start. The documented startup preparation (`python -m app.startup`, also included in the container command) therefore clears locally mirrored campaigns and idempotency records in fake mode after migrations. This prevents durable database rows from referencing remote objects that vanished with the fake process. HTTP mode never performs this reset.

Push is protected by optimistic `draft_version`, a database row lock and `syncing`. Before PUT, the latest remote editable stream is fingerprinted. A mismatch returns `remote_changed`; the user keeps the draft and may cancel, inspect Keitaro, then Fetch. After PUT, the returned stream is normalized and stored. If the response is ambiguous, the draft remains and a refetch determines the outcome.

## 11. Configuration and secrets

Environment variables: `DATABASE_URL`, `KEITARO_MODE`, `KEITARO_BASE_URL`, `KEITARO_API_KEY`, `KEITARO_DOMAIN_ID`, `KEITARO_GROUP_ID`, `KEITARO_TRAFFIC_SOURCE_ID`, `KEITARO_GOOGLE_URL`, timeout/retry settings, and optional admin URL template.

`.env` is ignored; `.env.example` contains placeholders only. The client adds the key directly to the request header. Logs never include headers, environment dumps or full upstream bodies.

## 12. Logging and observability

Readable text logging is configured for the MVP. Each request receives/echoes `X-Request-ID`. Successful Keitaro calls log method, resource path, status and duration; headers and response bodies are excluded. Structured JSON logging and correlated request IDs inside log records are production follow-ups, not claimed as implemented. Health checks prove process readiness; DB/Keitaro deep checks are explicit operations to avoid making orchestration depend on a third party.

## 13. Test strategy

- pure unit tests: shares for 0/1/3/4/5 and stable fingerprints;
- payload tests: campaign, Google stream and offer stream shapes at the compatibility boundary;
- service/API tests with fake Keitaro: JSON-safe validation, create/idempotent replay, insert-race handling, safe preflight retry, ambiguous mutation outcome, draft transitions, cancel, successful push, failed push retains draft, double/stale push and remote conflict;
- `HttpKeitaroClient` tests with `MockTransport`: headers, GET retries, no mutation retry, status mapping, timeout/network failures, malformed JSON and unexpected success shapes;
- startup tests: fake mode clears the local mirror while HTTP mode preserves it;
- migration smoke test: upgrade an empty database to head;
- static checks: Ruff on application/tests and strict mypy on application code;
- browser smoke: create campaign, edit offers, cancel and push in fake mode.

Real Keitaro testing is a separate, opt-in smoke script because it creates external state. It must use a dedicated tracker and explicit IDs.

## 14. Repository structure

```text
app/                 FastAPI application
  keitaro/           real/fake clients and payload compatibility boundary
  templates/ static/ browser UI
alembic/             versioned schema migrations
tests/               unit, API, transport and concurrency tests
requirements*.lock   pinned runtime and test dependencies
SDD.md               this document
README.md             setup, operation and trade-offs
Dockerfile
docker-compose.yml
pyproject.toml
```

## 15. Implementation stages

1. Freeze verified API facts and assumptions in this SDD.
2. Add configuration, database model and initial migration.
3. Implement fake and HTTP Keitaro clients plus payload tests.
4. Implement create/import/fetch and idempotency.
5. Implement durable draft transitions, conflict detection and guarded Push.
6. Build the two-page UI and honest Stats/Trends placeholders.
7. Run tests, type/static checks, migration smoke and browser smoke in Docker.
8. Review secrets, README and clean-clone instructions.

## 16. Risks and acceptance criteria

Primary risk is Keitaro version-specific stream payloads. It is isolated, documented and covered by fake/payload tests, but only a target-account smoke test closes it. Partial campaign creation is another risk; the result reports created IDs and does not perform undocumented destructive compensation. The deterministic concurrency regression test uses SQLite WAL plus the same database unique constraint; final migration and live behavior are also exercised against Compose PostgreSQL, but a high-load PostgreSQL race test remains outside this MVP.

Accepted when:

- a clean clone starts in fake mode with documented commands;
- migrations apply to PostgreSQL;
- campaign creation validates inputs and produces two correctly purposed streams in fake mode;
- editor implements fetch, add, remove, bring back, cancel, view and one guarded push;
- Google stream is never mutated;
- shares meet all stated examples and never permit a zero-offer push;
- failed push retains the draft; successful push clears it;
- external-change and double-push conflicts are explicit;
- secrets are absent from Git and logs;
- tests and static checks pass;
- README distinguishes verified Keitaro API facts from deployment assumptions.

