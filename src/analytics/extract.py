"""`analytics extract finance`: read the source tables and write one Parquet file per table."""

from dataclasses import dataclass
from datetime import UTC, datetime

from analytics.finance_tables import FINANCE_TABLES, OPTIONAL_TABLES
from analytics.settings import Settings
from analytics.sources import Source
from analytics.warehouse import RAW_FINANCE, connect, ensure_meta, run_id_for


@dataclass
class ExtractResult:
    run_id: str
    rows: dict[str, int]


def extract_finance(
    source: Source, settings: Settings, now: datetime | None = None
) -> ExtractResult:
    started = (now or datetime.now(UTC)).astimezone(UTC)
    run_id = run_id_for(started)
    out_dir = settings.data_dir / "raw" / RAW_FINANCE / run_id
    out_dir.mkdir(parents=True, exist_ok=False)

    rows: dict[str, int] = {}
    error: str | None = None
    try:
        for table in FINANCE_TABLES:
            df = source.read(table.query)
            df.write_parquet(out_dir / f"{table.raw_name}.parquet")
            rows[table.raw_name] = df.height
        for table in OPTIONAL_TABLES:
            try:
                df = source.read(table.query)
            except (
                Exception
            ):  # the source has no such view (an older FinancePowerApp): nothing is lost
                continue
            df.write_parquet(out_dir / f"{table.raw_name}.parquet")
            rows[table.raw_name] = df.height
    except Exception as exc:
        # Type and first line only: never echo a connection string or row content into the log.
        error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}"
        raise
    finally:
        _record(settings, run_id, started, rows, error)
    return ExtractResult(run_id, rows)


def _record(
    settings: Settings, run_id: str, started: datetime, rows: dict[str, int], error: str | None
) -> None:
    con = connect(settings.warehouse_path)
    try:
        ensure_meta(con)
        con.execute(
            "INSERT INTO meta.load_run VALUES (?, 'finance', ?, ?, ?, ?)",
            [
                run_id,
                started.replace(tzinfo=None),
                datetime.now(UTC).replace(tzinfo=None),
                "failed" if error else "succeeded",
                error,
            ],
        )
        for name, count in rows.items():
            con.execute("INSERT INTO meta.load_run_table VALUES (?, ?, ?)", [run_id, name, count])
    finally:
        con.close()
