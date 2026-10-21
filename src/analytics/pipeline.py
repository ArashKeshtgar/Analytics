"""`analytics run` (phase 6): extract, build, score and a data-quality report, as one run.

The warehouse the API reads is never built in place. The run copies it to
`data/next/warehouse.duckdb`, extracts, builds and scores there, and only when that worked
replaces the live file with it. So the dashboard keeps the last good data while a run is under
way or after it failed, and the API's reads never meet dbt's writes (DuckDB lets one process write
a file, or many read it, not both).

Each run's report is a JSON file in `data/runs/` (not in the warehouse, so a failed run is reported
too): the steps, the row count of every table against the last successful run, the dbt tests that
did not pass, and the warnings drawn from them. `GET /api/meta/runs` serves them.
"""

import json
import os
import shutil
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from analytics.alerts import notify
from analytics.extract import extract_finance
from analytics.reconcile import Reconciler, sql_server_reconcile
from analytics.retention import prune
from analytics.scoring import score
from analytics.settings import Settings
from analytics.sources import SqlServerSource
from analytics.warehouse import build, complete_runs, run_id_for

# A table whose rows fell by more than this share since the last good run is a warning.
DROP_WARNING = 0.2
# ...when it had at least this many rows (a table of 3 losing one is not news).
DROP_MIN_ROWS = 10
COUNTED_SCHEMAS = ("raw", "main")

Extractor = Callable[[Settings], dict[str, int]]


@dataclass
class Step:
    name: str
    status: str  # ok, skipped, failed
    seconds: float
    detail: str = ""


@dataclass
class Check:
    level: str  # warning or error
    kind: str  # dbt-test, empty-table, row-drop, step
    subject: str
    message: str


@dataclass
class Report:
    run_id: str
    started_utc: str
    finished_utc: str = ""
    status: str = "running"  # ok, warning (finished with warnings), failed
    steps: list[Step] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)  # name, rows, previous
    failed_tests: list[dict[str, Any]] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    warehouse_replaced: bool = False
    alert: str = ""  # what the webhook was told about this run: failed, recovered or nothing


def runs_dir(settings: Settings) -> Path:
    return settings.data_dir / "runs"


def next_path(settings: Settings) -> Path:
    """Beside the live file, under the same name: dbt-duckdb names the database after the file."""
    live = settings.warehouse_path
    return live.parent / "next" / live.name


def sql_server_extract(settings: Settings) -> dict[str, int]:
    source = SqlServerSource(settings.finance_connection_string)
    try:
        return extract_finance(source, settings).rows
    finally:
        source.close()


def load_reports(settings: Settings) -> list[dict[str, Any]]:
    """Every report on disk, newest first."""
    folder = runs_dir(settings)
    if not folder.is_dir():
        return []
    reports = []
    for path in sorted(folder.glob("*.json"), reverse=True):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return reports


def last_good_counts(settings: Settings) -> dict[str, int]:
    for report in load_reports(settings):
        if report.get("warehouse_replaced"):
            return {t["name"]: t["rows"] for t in report.get("tables", [])}
    return {}


def table_counts(path: Path) -> dict[str, int]:
    con = duckdb.connect(str(path), read_only=True)
    try:
        names = con.execute(
            "select table_schema || '.' || table_name from information_schema.tables "
            f"where table_schema in {COUNTED_SCHEMAS} order by 1"
        ).fetchall()
        counts = {}
        for (name,) in names:
            schema, table = name.split(".", 1)
            row = con.execute(f'select count(*) from "{schema}"."{table}"').fetchone()
            counts[name] = int(row[0]) if row else 0
        return counts
    finally:
        con.close()


def results_file(settings: Settings) -> Path:
    """dbt's run_results.json, where `run_dbt` points dbt's target folder."""
    return (settings.data_dir / "dbt" / "target" / "run_results.json").resolve()


def dbt_failures(settings: Settings) -> list[dict[str, Any]]:
    """Tests and models of the last dbt invocation that did not pass (run_results.json)."""
    path = results_file(settings)
    if not path.is_file():
        return []
    results = json.loads(path.read_text(encoding="utf-8")).get("results", [])
    return [
        {
            "node": r.get("unique_id", ""),
            "status": r.get("status", ""),
            "failures": r.get("failures"),
            "message": (r.get("message") or "")[:300],
        }
        for r in results
        if r.get("status") in ("fail", "error", "warn")
    ]


def checks_for(
    counts: dict[str, int], previous: dict[str, int], failures: list[dict[str, Any]]
) -> list[Check]:
    checks: list[Check] = []
    for f in failures:
        level = "warning" if f["status"] == "warn" else "error"
        kind = "dbt-test" if f["node"].startswith("test.") else "dbt-model"
        checks.append(Check(level, kind, f["node"], f"{f['status']}: {f['message']}".strip()))
    for name, before in sorted(previous.items()):
        now = counts.get(name)
        if now is None:
            continue
        if before > 0 and now == 0:
            checks.append(
                Check("warning", "empty-table", name, f"{before} rows last time, none now")
            )
        elif before >= DROP_MIN_ROWS and now < before * (1 - DROP_WARNING):
            checks.append(Check("warning", "row-drop", name, f"{before} rows last time, {now} now"))
    return checks


def _step(report: Report, name: str, fn: Callable[[], str]) -> bool:
    started = time.monotonic()
    try:
        detail = fn()
    except Exception as exc:  # the run records it and stops; nothing is raised to the scheduler
        first = str(exc).splitlines()[0][:200] if str(exc) else ""
        report.steps.append(
            Step(
                name,
                "failed",
                round(time.monotonic() - started, 2),
                f"{type(exc).__name__}: {first}",
            )
        )
        report.checks.append(Check("error", "step", name, f"{type(exc).__name__}: {first}"))
        return False
    status = "skipped" if detail.startswith("skipped") else "ok"
    report.steps.append(Step(name, status, round(time.monotonic() - started, 2), detail))
    return True


def _replace(src: Path, dest: Path, attempts: int = 20, pause: float = 0.5) -> None:
    """Swaps the new warehouse in; on Windows a reader may hold the file for a moment, so retry."""
    for i in range(attempts):
        try:
            os.replace(src, dest)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(pause)


def run(
    settings: Settings,
    now: datetime | None = None,
    extractor: Extractor | None = None,
    reconciler: Reconciler | None = None,
) -> Report:
    started = (now or datetime.now(UTC)).astimezone(UTC)
    report = Report(run_id=run_id_for(started), started_utc=started.isoformat())
    live, aside = settings.warehouse_path, next_path(settings)
    work = settings.model_copy(update={"warehouse_path": aside})

    def prepare() -> str:
        aside.parent.mkdir(parents=True, exist_ok=True)
        aside.unlink(missing_ok=True)
        if live.is_file():
            shutil.copyfile(live, aside)
            return "copied the live warehouse"
        return "no warehouse yet: a new one"

    def extract() -> str:
        if extractor is None and not settings.finance_connection_string:
            return "skipped: ANALYTICS_FINANCE_CONNECTION_STRING is not set"
        rows = (extractor or sql_server_extract)(work)
        return f"{len(rows)} tables, {sum(rows.values())} rows"

    def build_step() -> str:
        # The report reads dbt's results file: never last run's, when this run's dbt did not start.
        results_file(work).unlink(missing_ok=True)
        if not complete_runs(work):
            raise RuntimeError(
                "no finance extract yet: set ANALYTICS_FINANCE_CONNECTION_STRING "
                "(or run `analytics extract finance`)"
            )
        if build(work) != 0:
            raise RuntimeError("dbt build failed: see the failed tests and the dbt log")
        return "models and tests passed"

    def reconcile_step() -> str:
        # Only against the books this run just read (the extract and these queries: seconds apart).
        if reconciler is None and (extractor is not None or not settings.finance_connection_string):
            return "skipped: nothing extracted from FinancePowerApp in this run"
        result = (reconciler or sql_server_reconcile)(work)
        report.checks.extend(
            Check("warning", "reconcile", d.subject(), d.message()) for d in result.differences
        )
        return result.describe()

    def score_step() -> str:
        s = score(work)
        return f"{s.forecasts} of {s.series} series forecast, {s.flagged} remittance flags"

    ok = _step(report, "prepare", prepare) and _step(report, "extract", extract)
    built = ok and _step(report, "build", build_step)
    # The tests that failed are worth reporting even when the build as a whole failed.
    report.failed_tests = dbt_failures(work) if ok else []
    if built:
        # A difference, or a reconciliation that could not run, is reported; the run goes on.
        _step(report, "reconcile", reconcile_step)
    scored = built and _step(report, "score", score_step)
    previous = last_good_counts(settings)
    if aside.is_file() and ok:
        try:
            counts = table_counts(aside)
        except duckdb.Error:
            counts = {}
        report.tables = [
            {"name": n, "rows": c, "previous": previous.get(n)} for n, c in sorted(counts.items())
        ]
        report.checks += checks_for(counts, previous, report.failed_tests)
    if scored and _step(report, "replace", lambda: _replace_detail(aside, live)):
        report.warehouse_replaced = True
    else:
        aside.unlink(missing_ok=True)
    # Old data goes after every run, a failed one too (its partial extract is the first to go).
    _step(report, "prune", lambda: prune(settings, now=started).describe())
    report.finished_utc = datetime.now(UTC).isoformat()
    if not report.warehouse_replaced:
        report.status = "failed"
    else:
        report.status = "warning" if report.checks else "ok"
    report.alert = notify(report, load_reports(settings), settings)
    write_report(settings, report)
    return report


def _replace_detail(aside: Path, live: Path) -> str:
    _replace(aside, live)
    return "the dashboard now reads this run"


def write_report(settings: Settings, report: Report) -> Path:
    folder = runs_dir(settings)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report.run_id}.json"
    temp = folder / f".{path.name}.tmp"
    temp.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    os.replace(temp, path)
    return path


def describe_failure(exc: BaseException) -> str:
    """For the scheduler's log: the exception type and its first line, never a connection string."""
    lines = traceback.format_exception_only(type(exc), exc)
    return lines[-1].strip()[:200] if lines else type(exc).__name__
