# Working on Analytics

- The plan is [docs/architecture.md](docs/architecture.md). Work one phase at a time, in order. When a phase is done,
  mark it **Done** there and tick it in the README. Say plainly when a promised piece is not built.
- The sources are other applications (.NET, SQL Server) in other repositories, usually not available in this
  session; [docs/sources.md](docs/sources.md) is the reference. If a column or table is not known, write the question
  in docs/sources.md instead of guessing. When a phase needs a change in another repository, list it under that phase.
- Read-only: never write to a source. No health information: no names, health card numbers, birth dates, diagnoses,
  notes or result values, ever — not in the warehouse, logs or fixtures. Test data is synthetic.
- Every change comes with tests. Before committing: `uv run ruff check`, `uv run mypy src`, `uv run pytest`,
  and `dbt build` for model changes.
- Ports: API 5600, web 5601. Docs in English, in the plain style of the ClinicHub docs.
