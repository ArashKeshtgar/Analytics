from datetime import UTC, datetime
from pathlib import Path

import duckdb
import polars as pl
import pytest

from analytics.extract import extract_finance
from analytics.finance_tables import FINANCE_TABLES, FORBIDDEN_COLUMNS
from analytics.settings import Settings
from analytics.sources import DuckDbSource
from tests import synthetic_source

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        warehouse_path=tmp_path / "data" / "warehouse.duckdb",
        _env_file=None,  # type: ignore[call-arg]
    )


def test_no_table_selects_a_forbidden_column() -> None:
    for table in FINANCE_TABLES:
        assert not FORBIDDEN_COLUMNS & set(table.columns), table.raw_name


def test_queries_are_plain_selects_without_star() -> None:
    for table in FINANCE_TABLES:
        assert table.query.startswith('SELECT "')
        assert "*" not in table.query


def test_extract_writes_one_parquet_per_table_without_personal_columns(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    result = extract_finance(DuckDbSource(synthetic_source.create()), settings, now=NOW)

    run_dir = settings.data_dir / "raw" / "finance" / "20261031T120000Z"
    assert result.run_id == "20261031T120000Z"
    assert sorted(p.stem for p in run_dir.glob("*.parquet")) == sorted(
        synthetic_source.table_names()
    )
    assert result.rows["org_party"] == 5
    assert result.rows["gl_journalline"] == 14

    party = pl.read_parquet(run_dir / "org_party.parquet")
    assert "Email" not in party.columns and "Phone" not in party.columns
    entry = pl.read_parquet(run_dir / "gl_journalentry.parquet")
    assert "Memo" not in entry.columns and "CreatedBy" not in entry.columns
    item = pl.read_parquet(run_dir / "ar_item.parquet")
    assert "Reference" not in item.columns


def test_extract_logs_the_run(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    extract_finance(DuckDbSource(synthetic_source.create()), settings, now=NOW)
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    run = con.execute("select run_id, source, status, error from meta.load_run").fetchall()
    counts = dict(con.execute("select table_name, row_count from meta.load_run_table").fetchall())
    assert run == [("20261031T120000Z", "finance", "succeeded", None)]
    assert counts["ar_item"] == 3 and counts["dbo_accountingperiods"] == 2


class BrokenSource:
    def read(self, query: str) -> pl.DataFrame:
        raise RuntimeError("login failed for user 'x' password=hunter2\nsecond line")

    def close(self) -> None:
        pass


def test_failed_run_is_logged_without_leaking_detail_beyond_first_line(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with pytest.raises(RuntimeError):
        extract_finance(BrokenSource(), settings, now=NOW)
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    status, error = con.execute("select status, error from meta.load_run").fetchone()  # type: ignore[misc]
    assert status == "failed"
    assert error.startswith("RuntimeError") and "second line" not in error
