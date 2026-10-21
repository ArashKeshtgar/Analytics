"""`analytics score` on a small hand-built warehouse (tests/ml_warehouse.py)."""

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from analytics.cli import app
from analytics.forecast import BASELINE
from analytics.scoring import ScoreError, score
from analytics.settings import Settings
from tests import ml_warehouse
from tests.conftest import make_settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = make_settings(tmp_path)
    ml_warehouse.create(s.warehouse_path)
    return s


def rows(settings: Settings, sql: str) -> list[tuple]:
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_a_run_forecasts_what_is_long_enough_and_says_what_is_not(settings: Settings) -> None:
    run = score(settings, as_of=ml_warehouse.AS_OF, now=datetime(2026, 10, 16, 3, tzinfo=UTC))

    assert run.data_through == ml_warehouse.THROUGH
    assert (run.series, run.forecasts, run.too_short) == (3, 2, 1)
    status = rows(
        settings,
        "select business_id, line_of_business, months, status, model "
        "from ml.forecast_series order by 1, 2",
    )
    assert [(b, line, n, st) for b, line, n, st, _ in status] == [
        (1, "Clinic", 48, "forecast"),
        (1, "Pharmacy", 10, "too-short"),
        (2, "Clinic", 30, "forecast"),
    ]
    assert status[1][4] is None

    # Six months from October 2026, the first month not in the data (October's row is ignored).
    months = rows(settings, "select month, step from ml.forecast where business_id = 1 order by 2")
    assert [m for m, _ in months] == [date(2026, m, 1) for m in (10, 11, 12)] + [
        date(2027, m, 1) for m in (1, 2, 3)
    ]
    assert (
        rows(
            settings, "select count(*) from ml.forecast where lower > forecast or upper < forecast"
        )[0][0]
        == 0
    )


def test_every_candidate_is_backtested_and_exactly_one_is_chosen(settings: Settings) -> None:
    score(settings, as_of=ml_warehouse.AS_OF)
    tested = rows(
        settings,
        "select model, origins, mase, chosen from ml.backtest "
        "where business_id = 1 and line_of_business = 'Clinic' order by model",
    )
    assert {m for m, *_ in tested} == {BASELINE, "ets", "sarima", "gradient-boosting"}
    assert all(o == 6 for _, o, _, _ in tested)
    chosen = [m for m, _, _, c in tested if c]
    assert len(chosen) == 1
    mase = {m: v for m, _, v, _ in tested}
    assert mase[chosen[0]] <= mase[BASELINE]
    model = rows(
        settings,
        "select model from ml.forecast_series "
        "where business_id = 1 and line_of_business = 'Clinic'",
    )
    assert model[0][0] == chosen[0]


def test_the_remittance_spike_is_flagged_and_the_unfinished_month_is_not_scored(
    settings: Settings,
) -> None:
    run = score(settings, as_of=ml_warehouse.AS_OF)
    assert run.flagged == 1
    flagged = rows(
        settings,
        "select provider, month, measure, rate, usual_rate, history_months "
        "from ml.remittance_score where flagged",
    )
    assert flagged == [
        ("123456", date(2026, 9, 1), "short_paid", pytest.approx(0.10), pytest.approx(0.0125), 8)
    ]
    assert (
        rows(settings, "select count(*) from ml.remittance_score where month > DATE '2026-09-01'")[
            0
        ][0]
        == 0
    )


def test_runs_are_kept_side_by_side(settings: Settings) -> None:
    first = score(settings, as_of=ml_warehouse.AS_OF, now=datetime(2026, 10, 16, 3, tzinfo=UTC))
    second = score(settings, as_of=ml_warehouse.AS_OF, now=datetime(2026, 10, 17, 3, tzinfo=UTC))
    assert first.run_id != second.run_id
    assert rows(settings, "select count(*) from ml.run")[0][0] == 2
    per_run = rows(settings, "select run_id, count(*) from ml.forecast group by 1 order by 1")
    assert [n for _, n in per_run] == [12, 12]


def test_without_a_built_warehouse_it_says_so(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with pytest.raises(ScoreError):
        score(settings, as_of=date(2026, 10, 1))
    result = CliRunner().invoke(
        app,
        ["score"],
        env={
            "ANALYTICS_DATA_DIR": str(tmp_path / "data"),
            "ANALYTICS_WAREHOUSE_PATH": str(settings.warehouse_path),
        },
    )
    assert result.exit_code == 2 and "analytics build" in result.output


def test_the_command_reports_the_run(settings: Settings) -> None:
    result = CliRunner().invoke(
        app,
        ["score"],
        env={
            "ANALYTICS_DATA_DIR": str(settings.data_dir),
            "ANALYTICS_WAREHOUSE_PATH": str(settings.warehouse_path),
        },
    )
    assert result.exit_code == 0, result.output
    assert "revenue series: 3" in result.output
    assert "flagged" in result.output


def test_it_runs_on_the_marts_dbt_builds(built: Settings, tmp_path: Path) -> None:
    """The real models (synthetic source): two months of books, so everything is too short."""
    import shutil

    copy = make_settings(tmp_path)
    copy.warehouse_path.parent.mkdir(parents=True)
    shutil.copy(built.warehouse_path, copy.warehouse_path)
    run = score(copy, as_of=date(2026, 11, 15))
    assert run.series > 0 and run.forecasts == 0 and run.too_short == run.series
    assert rows(copy, "select distinct status from ml.forecast_series") == [("too-short",)]
