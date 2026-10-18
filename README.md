# Analytics

Reporting and forecasting for the [ClinicHub](https://github.com/ArashKeshtgar/ClinicHub) platform: the group's money
from FinancePowerApp and the clinics' operations from [IntegrationHub](https://github.com/ArashKeshtgar/IntegrationHub)'s
de-identified event feed, in one warehouse, with a dashboard per clinic and for the group, and forecasts judged
against a baseline. Read-only: it never writes to another application. No health information enters it.

Python 3.12 · FastAPI · DuckDB · dbt · Polars · statsmodels / scikit-learn · React + Vite.

- Plan and phases: [docs/architecture.md](docs/architecture.md)
- What it reads: [docs/sources.md](docs/sources.md)

## Status

- [ ] Phase 0 — skeleton, CLI, CI, Docker
- [ ] Phase 1 — finance warehouse from FinancePowerApp, dbt marts, API
- [ ] Phase 2 — sign-in through ClinicHub, clinic-scoped access
- [ ] Phase 3 — dashboard: revenue, OHIP collection, receivables, HST
- [ ] Phase 4 — operations from IntegrationHub events: turnaround, cancellations
- [ ] Phase 5 — revenue forecasts and remittance anomalies, with backtests
- [ ] Phase 6 — scheduled runs, data-quality report, platform compose

All data in tests and samples is synthetic.
