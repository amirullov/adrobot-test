# Adrobot Keitaro Wrapper

A compact FastAPI application for creating a two-stream Keitaro campaign and safely editing the offer list of an existing campaign. It includes PostgreSQL, SQLAlchemy 2, Alembic migrations, a server-rendered browser UI, a real Admin API adapter and a deterministic fake mode.

The design and trade-offs are documented in [SDD.md](SDD.md).

## What works

- Create a campaign from name, ISO country code and offer.
- Apply configured domain, campaign group and traffic source IDs.
- Create a country-filtered Google stream and fallback offer stream.
- Import/fetch an existing campaign and edit only its offer stream.
- Add, remove, bring back and cancel in a durable local draft.
- Keep removed rows visible with 0% share.
- Push one complete offer list, with stale draft, double-push and external-change protection.
- Allocate deterministic shares: 1 → 100; 3 → 34/33/33; 4 → 25 each; 5 → 20 each. Zero active offers cannot be pushed.
- Run the entire workflow without a Keitaro account using fake mode.

Stats and Trends intentionally display `—`. No reporting period, metrics or verified reporting contract was supplied, so the project does not invent data.

## Technology choice

The backend and pages are one FastAPI monolith. Jinja templates plus small vanilla JavaScript files are enough for two workflows and avoid a separate Node build/deployment surface. PostgreSQL is the runtime database; SQLite is used for fast isolated tests. No queue, Redis or background worker is needed because Push is an immediate user action.

## Quick start with Docker Compose

Requirements: Docker Desktop/Engine with Compose.

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open [http://localhost:8000](http://localhost:8000). The example configuration starts in `KEITARO_MODE=fake`; import campaign `5001` to try the editor immediately.

The app container waits for PostgreSQL, applies `alembic upgrade head`, then starts Uvicorn. Stop with `Ctrl+C`; remove containers with `docker compose down`. The named PostgreSQL volume is retained. Use `docker compose down -v` only when you intentionally want to erase local database data.

## Local Python start

Python 3.12+ and PostgreSQL are recommended.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
# Set DATABASE_URL to a reachable PostgreSQL URL, then:
alembic upgrade head
uvicorn app.main:app --reload
```

For a short no-Docker demo, set `DATABASE_URL=sqlite:///./adrobot.db`; migrations support it.

## Real Keitaro configuration

Set these in `.env` (which is ignored by Git):

```dotenv
KEITARO_MODE=http
KEITARO_BASE_URL=https://your-tracker.example.com
KEITARO_API_KEY=...
KEITARO_DOMAIN_ID=...
KEITARO_GROUP_ID=...
KEITARO_TRAFFIC_SOURCE_ID=...
```

The API key is sent only in the `Api-Key` header and is not included in settings representations, responses or logs.

### Important compatibility check

The official Admin API reference confirms campaigns, campaign streams, offers, campaign `domain_id`/`group_id`/`traffic_source_id`, stream `offers` and partial stream update via `PUT /streams/{id}`. Keitaro payload semantics can vary by tracker version. Before creating real traffic state:

1. Open the target tracker's built-in Admin API Swagger or inspect a successful Admin UI request as Keitaro recommends.
2. Confirm stream creation is `POST /campaigns/{id}/streams`.
3. Confirm the country filter payload, redirect action type/payload, and offer action type.
4. If needed, change only `app/keitaro/payloads.py` and its tests.
5. Run a smoke test in a dedicated campaign/account.

The compatibility assumptions and verified facts are listed precisely in `SDD.md`; fake mode demonstrates application logic, not real-account compatibility.

## Migrations

```powershell
docker compose run --rm app alembic upgrade head
docker compose run --rm app alembic current
```

Create a new migration after a model change:

```powershell
docker compose run --rm app alembic revision --autogenerate -m "describe change"
```

Always review generated migrations before applying them.

## Tests and checks

```powershell
docker compose build app
docker compose run --rm app sh -lc "COVERAGE_FILE=/tmp/.coverage coverage run --source=app -m pytest && COVERAGE_FILE=/tmp/.coverage coverage report -m"
docker compose run --rm app ruff check app tests alembic
docker compose run --rm app mypy app
```

Tests cover share allocation, payload construction, idempotent campaign creation, all draft transitions, successful and failed Push, retained drafts, stale versions and remote conflicts.

## REST API

Interactive OpenAPI docs are at `/docs`. Main endpoints:

- `GET /api/offers?q=`
- `POST /api/campaigns` with `Idempotency-Key`
- `POST /api/campaigns/import`
- `POST /api/campaigns/{id}/fetch`
- draft add/remove/bring-back/cancel endpoints
- `POST /api/campaigns/{id}/push`

Errors have a stable shape:

```json
{"error":{"code":"remote_changed","message":"...","retryable":false,"details":null}}
```

## Failure behavior worth knowing

- Mutating Keitaro requests are not automatically retried because the upstream API does not document idempotency.
- Campaign creation requires an idempotency key. A successful replay returns the same local campaign.
- If creation partially succeeds, the response includes known created IDs and asks the operator to inspect Keitaro; the service does not perform an undocumented destructive rollback.
- A failed Push keeps the draft.
- If Keitaro changed after Fetch, Push returns `409 remote_changed` and keeps the draft.
- Fetch refuses to overwrite a dirty draft.
- A process crash during Push may leave `syncing=true`; for this MVP an operator inspects Keitaro and clears/reconciles the row. A production multi-replica version would use a time-bounded lease.

## Repository map

```text
app/api.py                 HTTP contracts
app/services.py            business rules and transaction boundaries
app/keitaro/http.py        real Admin API transport
app/keitaro/fake.py        local deterministic tracker
app/keitaro/payloads.py    version-sensitive Keitaro assumptions
app/templates, app/static  browser UI
alembic/                   migrations
tests/                     unit and API behavior
SDD.md                     detailed design and acceptance criteria
```

## AI use

AI was used for architecture alternatives, draft implementation, tests, edge-case review and documentation. A developer must still verify the target Keitaro payloads, stream behavior, allocation math, migration, error paths, secret handling, tests and a real launch. The project intentionally avoids layers and infrastructure that the author could not justify in an interview.
