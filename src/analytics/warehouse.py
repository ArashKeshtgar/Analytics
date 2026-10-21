"""The DuckDB warehouse: run log, loading raw extracts, running dbt."""

import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb

from analytics.events import EVENT_COLUMNS, events_dir
from analytics.finance_tables import FINANCE_TABLES, HISTORY_TABLES
from analytics.labflow_dw import load_labflow_dw
from analytics.settings import Settings

RAW_FINANCE = "finance"


def connect(path: Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def ensure_meta(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS meta")
    con.execute(
        """CREATE TABLE IF NOT EXISTS meta.load_run (
               run_id varchar PRIMARY KEY, source varchar NOT NULL,
               started_utc timestamp NOT NULL, finished_utc timestamp,
               status varchar NOT NULL, error varchar)"""
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS meta.load_run_table (
               run_id varchar NOT NULL, table_name varchar NOT NULL, row_count bigint NOT NULL)"""
    )


def run_id_for(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_date(run_id: str) -> date:
    return datetime.strptime(run_id, "%Y%m%dT%H%M%SZ").date()


def complete_runs(settings: Settings) -> list[str]:
    """Run ids (oldest first) whose directory holds every expected table."""
    base = settings.data_dir / "raw" / RAW_FINANCE
    if not base.is_dir():
        return []
    expected = [t.raw_name + ".parquet" for t in FINANCE_TABLES]
    return sorted(
        d.name for d in base.iterdir() if d.is_dir() and all((d / f).is_file() for f in expected)
    )


def _parquet(settings: Settings, run: str, table: str) -> str:
    path = settings.data_dir / "raw" / RAW_FINANCE / run / f"{table}.parquet"
    return str(path).replace("'", "''")


def load_raw(settings: Settings, con: duckdb.DuckDBPyConnection) -> list[str]:
    """Rebuild schema `raw` from the Parquet runs on disk. Returns the runs used.

    Current tables come from the latest run. The open-item history has one snapshot per calendar
    day (the last run of that day), so it can be rebuilt from scratch as long as the runs are kept.
    """
    runs = complete_runs(settings)
    if not runs:
        return []
    latest = runs[-1]
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    for table in FINANCE_TABLES:
        con.execute(
            f"CREATE OR REPLACE TABLE raw.{table.raw_name} AS "
            f"SELECT * FROM read_parquet('{_parquet(settings, latest, table.raw_name)}')"
        )
    last_of_day: dict[date, str] = {}
    for run in runs:
        last_of_day[run_date(run)] = run
    for name in HISTORY_TABLES:
        selects = [
            f"SELECT DATE '{day.isoformat()}' AS snapshot_date, * "
            f"FROM read_parquet('{_parquet(settings, run, name)}')"
            for day, run in sorted(last_of_day.items())
        ]
        con.execute(f"CREATE OR REPLACE TABLE raw.{name}_history AS " + " UNION ALL ".join(selects))
    return runs


_DUCKDB_TYPES = {
    "String": "VARCHAR",
    "Int32": "INTEGER",
    "Datetime": "TIMESTAMP",
}


def load_events(settings: Settings, con: duckdb.DuckDBPyConnection) -> int:
    """Rebuild raw.clinical_event from the Parquet files the consumer wrote: one row per event id.

    Delivery is at least once, so the same event can be in two files; the first one received wins.
    With no files the table is empty, so the models still build. Returns the number of events.
    """
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    columns = ", ".join(f"{name} {_duckdb_type(kind)}" for name, kind in EVENT_COLUMNS.items())
    files = sorted(events_dir(settings).glob("events-*.parquet"))
    if not files:
        con.execute("DROP TABLE IF EXISTS raw.clinical_event")
        con.execute(f"CREATE TABLE raw.clinical_event ({columns})")
        return 0
    pattern = str(events_dir(settings) / "events-*.parquet").replace("'", "''")
    con.execute(
        "CREATE OR REPLACE TABLE raw.clinical_event AS "
        f"SELECT * FROM read_parquet('{pattern}') "
        "QUALIFY row_number() OVER (PARTITION BY event_id ORDER BY received_at) = 1"
    )
    row = con.execute("SELECT count(*) FROM raw.clinical_event").fetchone()
    return int(row[0]) if row else 0


def _duckdb_type(kind: Any) -> str:
    return _DUCKDB_TYPES[str(kind).split("(")[0]]


def run_dbt(settings: Settings, command: str = "build") -> int:
    dbt = Path(sys.executable).parent / "dbt"
    work = (settings.data_dir / "dbt").resolve()
    work.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "ANALYTICS_WAREHOUSE_PATH": str(settings.warehouse_path.resolve()),
        "DBT_TARGET_PATH": str(work / "target"),
        "DBT_LOG_PATH": str(work / "logs"),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }
    project = str(settings.dbt_project_dir)
    result = subprocess.run(
        [str(dbt), command, "--project-dir", project, "--profiles-dir", project],
        env=env,
        check=False,
    )
    return result.returncode


def build(settings: Settings) -> int:
    """Load the raw extracts into the warehouse and run dbt. Non-zero when nothing was extracted
    or a dbt model or test fails."""
    con = connect(settings.warehouse_path)
    try:
        ensure_meta(con)
        runs = load_raw(settings, con)
        load_events(settings, con)
        load_labflow_dw(settings, con)
    finally:
        con.close()
    if not runs:
        print(
            "No finance extract found under "
            f"{settings.data_dir / 'raw' / RAW_FINANCE}. Run `analytics extract finance` first.",
            file=sys.stderr,
        )
        return 1
    return run_dbt(settings)
