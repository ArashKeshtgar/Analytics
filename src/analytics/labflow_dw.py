"""LabFlow's warehouse (`dw`, the legacy lab's history) as a second source, for lab volumes
(phase 4's optional source, built in phase 6).

Only monthly totals leave LabFlow: its view `dw.vw_AnalyticsMonthly` counts results, visits,
abnormal and critical results and turnaround per month, test and kind of payer, and the read-only
login `analytics_dw_reader` may read that view and the test catalogue's names and codes, nothing
else (LabFlow's `database/054_analytics_dw_view.sql` and
`database/tools/analytics_dw_reader.sql`). The warehouse's dates are shifted by its ETL (up to 180
days either way) to de-identify it, so its months are approximate.

Each extract replaces the last one (`data/raw/labflow_dw/`): there is no history to keep.
"""

import shutil
from collections.abc import Callable
from pathlib import Path

import duckdb

from analytics.finance_tables import SourceTable
from analytics.settings import Settings
from analytics.sources import Source, SqlServerSource

DW_TABLES = (
    SourceTable(
        "dw",
        "vw_AnalyticsMonthly",
        (
            "Year",
            "Month",
            "TestKey",
            "PayerType",
            "Results",
            "Visits",
            "Answered",
            "Abnormal",
            "Critical",
            "TurnaroundDaysSum",
            "TurnaroundCount",
        ),
    ),
    SourceTable(
        "dw", "DimTest", ("TestKey", "LoincCode", "LabFlowCode", "TestName", "Section", "IsPanel")
    ),
)

# The warehouse tables when nothing was ever extracted, so the models still build (empty).
_EMPTY = {
    "dw_vw_analyticsmonthly": (
        "Year integer, Month integer, TestKey integer, PayerType varchar, Results bigint, "
        "Visits bigint, Answered bigint, Abnormal bigint, Critical bigint, "
        "TurnaroundDaysSum bigint, TurnaroundCount bigint"
    ),
    "dw_dimtest": (
        "TestKey integer, LoincCode varchar, LabFlowCode varchar, TestName varchar, "
        "Section integer, IsPanel boolean"
    ),
}

DwExtractor = Callable[[Settings], dict[str, int]]


def dw_dir(settings: Settings) -> Path:
    return settings.data_dir / "raw" / "labflow_dw"


def extract_labflow_dw(source: Source, settings: Settings) -> dict[str, int]:
    """Writes one Parquet file per table into a new folder, then puts it in place of the last."""
    final = dw_dir(settings)
    work = final.with_name(final.name + ".next")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rows: dict[str, int] = {}
    for table in DW_TABLES:
        df = source.read(table.query)
        df.write_parquet(work / f"{table.raw_name}.parquet")
        rows[table.raw_name] = df.height
    shutil.rmtree(final, ignore_errors=True)
    work.rename(final)
    return rows


def sql_server_dw_extract(settings: Settings) -> dict[str, int]:
    source = SqlServerSource(settings.labflow_dw_connection_string)
    try:
        return extract_labflow_dw(source, settings)
    finally:
        source.close()


def load_labflow_dw(settings: Settings, con: duckdb.DuckDBPyConnection) -> bool:
    """Rebuilds raw.dw_* from the last extract, or empty tables without one. True when loaded."""
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    folder = dw_dir(settings)
    present = all((folder / f"{name}.parquet").is_file() for name in _EMPTY)
    for name, columns in _EMPTY.items():
        if present:
            path = str(folder / f"{name}.parquet").replace("'", "''")
            con.execute(
                f"CREATE OR REPLACE TABLE raw.{name} AS SELECT * FROM read_parquet('{path}')"
            )
        else:
            con.execute(f"CREATE OR REPLACE TABLE raw.{name} ({columns})")
    return present
