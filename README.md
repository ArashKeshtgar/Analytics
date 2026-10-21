# Analytics

Reporting and forecasting for the [ClinicHub](https://github.com/ArashKeshtgar/ClinicHub) platform: the group's money
from FinancePowerApp and the clinics' operations from [IntegrationHub](https://github.com/ArashKeshtgar/IntegrationHub)'s
de-identified event feed, in one warehouse, with a dashboard per clinic and for the group, and forecasts judged
against a baseline. Read-only: it never writes to another application. No health information enters it.

Python 3.12 · FastAPI · DuckDB · dbt · Polars · statsmodels / scikit-learn · React + Vite.

- Plan and phases: [docs/architecture.md](docs/architecture.md)
- What it reads: [docs/sources.md](docs/sources.md)

## Run it

Needs Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```
uv sync
cp .env.example .env
uv run analytics serve            # API on :5600
curl localhost:5600/healthz
# the finance endpoints need a ClinicHub access token: curl -H "Authorization: Bearer $TOKEN" localhost:5600/api/me
uv run analytics extract finance  # needs ANALYTICS_FINANCE_CONNECTION_STRING
uv run analytics consume --drain  # read IntegrationHub's events from RabbitMQ (without --drain: keep running)
uv run analytics build            # raw -> data/warehouse.duckdb -> dbt models and tests
uv run analytics score            # forecasts with backtests and remittance anomalies -> schema ml
uv run analytics run              # all of it into a copy of the warehouse, swapped in when it worked, plus a report in data/runs/
uv run analytics schedule         # run now and every ANALYTICS_RUN_EVERY (6h)
```

The dashboard (phase 3) is in `web/` ([web/README.md](web/README.md)): `cd web && npm ci && npm run dev` on :5601,
signed in through ClinicHub.

Checks before committing: `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`, `uv run pytest`.
Images: `docker build -t analytics .` and `docker build -t analytics-web web` (both in CI); the platform compose is ControlPanel's `compose.apps.yml` (includes the SQL Server ODBC driver, used from phase 1).

## Status

- [x] Phase 0 — skeleton, CLI, CI, Docker
- [x] Phase 1 — finance warehouse from FinancePowerApp, dbt marts, API
- [x] Phase 2 — sign-in through ClinicHub, clinic-scoped access — API done; web sign-in comes with the web (phase 3)
- [x] Phase 3 — dashboard: revenue, OHIP collection, receivables, HST
- [x] Phase 4 — operations from IntegrationHub events: turnaround, cancellations
- [x] Phase 5 — revenue forecasts and remittance anomalies, with backtests and model cards ([docs/models](docs/models)); not yet run on real books
- [x] Phase 6 — `analytics run` / `analytics schedule`, a data-quality report per run (`/api/meta/runs`), images in CI, ControlPanel compose with the extract from FinancePowerApp's `analytics_reader` login, a webhook alert when a run fails (`ANALYTICS_ALERT_WEBHOOK_URL`), the Runs page, `analytics prune` for old extracts and reports, a reconciliation with FinancePowerApp's own reports on every run (`analytics reconcile`)

All data in tests and samples is synthetic.
