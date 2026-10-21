"""`analytics score`: forecasts and remittance anomalies from the built warehouse into schema `ml`.

Every run is kept (`ml.run`), with its backtests, so how well each model did can be compared over
time; the API reads the latest run. Only complete months are used: the month of the latest finance
extract may not be finished, so the data ends with the month before it.
"""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

import duckdb

from analytics import anomalies
from analytics.forecast import (
    HORIZON,
    forecast_series,
    last_complete_month,
    month_add,
    monthly_series,
)
from analytics.settings import Settings
from analytics.warehouse import complete_runs, connect, run_date, run_id_for

ML_TABLES = [
    """CREATE TABLE IF NOT EXISTS ml.run (
           run_id varchar PRIMARY KEY, created_utc timestamp NOT NULL, data_through date NOT NULL,
           series integer NOT NULL, forecasts integer NOT NULL, flagged integer NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ml.forecast_series (
           run_id varchar NOT NULL, business_id integer NOT NULL, line_of_business varchar NOT NULL,
           first_month date NOT NULL, months integer NOT NULL, status varchar NOT NULL,
           model varchar)""",
    """CREATE TABLE IF NOT EXISTS ml.backtest (
           run_id varchar NOT NULL, business_id integer NOT NULL, line_of_business varchar NOT NULL,
           model varchar NOT NULL, origins integer NOT NULL, horizon integer NOT NULL,
           mae double, mape double, mase double, chosen boolean NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ml.forecast (
           run_id varchar NOT NULL, business_id integer NOT NULL, line_of_business varchar NOT NULL,
           month date NOT NULL, step integer NOT NULL, model varchar NOT NULL,
           forecast double NOT NULL, lower double NOT NULL, upper double NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ml.remittance_score (
           run_id varchar NOT NULL, business_id integer NOT NULL, provider varchar NOT NULL,
           month date NOT NULL, measure varchar NOT NULL, billed double NOT NULL,
           amount double NOT NULL, rate double NOT NULL, usual_rate double NOT NULL,
           spread double NOT NULL, history_months integer NOT NULL, z double,
           above_any_spread boolean NOT NULL, flagged boolean NOT NULL)""",
]


class ScoreError(Exception):
    """The warehouse has no marts to score (not built yet)."""


@dataclass
class ScoreRun:
    run_id: str
    data_through: date
    series: int
    forecasts: int
    too_short: int
    scored: int
    flagged: int


def ensure_ml(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS ml")
    for ddl in ML_TABLES:
        con.execute(ddl)


def data_as_of(settings: Settings) -> date:
    """The day of the latest finance extract (today when there is none)."""
    runs = complete_runs(settings)
    return run_date(runs[-1]) if runs else datetime.now(UTC).date()


def score(settings: Settings, as_of: date | None = None, now: datetime | None = None) -> ScoreRun:
    through = last_complete_month(as_of or data_as_of(settings))
    started = now or datetime.now(UTC)
    run_id = run_id_for(started)
    con = connect(settings.warehouse_path)
    try:
        try:
            revenue = con.execute(
                "select business_id, line_of_business, month, sum(revenue)::double "
                "from main.mart_revenue_monthly group by 1, 2, 3 order by 1, 2, 3"
            ).fetchall()
            ohip = con.execute(
                "select business_id, provider_code, month, billed::double, short_paid::double, "
                "refused::double from main.mart_ohip_provider_monthly"
            ).fetchall()
        except duckdb.CatalogException as exc:
            raise ScoreError("The warehouse is not built yet. Run `analytics build`.") from exc
        ensure_ml(con)
        con.execute("BEGIN")
        result = _forecasts(con, run_id, revenue, through)
        scores = anomalies.score(
            [anomalies.ProviderMonth(b, p, m, bl, sp, rf) for b, p, m, bl, sp, rf in ohip],
            through=through,
        )
        _write_scores(con, run_id, scores)
        flagged = sum(s.flagged for s in scores)
        con.execute(
            "INSERT INTO ml.run VALUES (?, ?, ?, ?, ?, ?)",
            [run_id, started.replace(tzinfo=None), through, result[0], result[1], flagged],
        )
        con.execute("COMMIT")
    finally:
        con.close()
    return ScoreRun(
        run_id, through, result[0], result[1], result[0] - result[1], len(scores), flagged
    )


def _forecasts(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    rows: list[tuple[int, str, date, float]],
    through: date,
) -> tuple[int, int]:
    """Writes every series' status, backtests and forecast. Returns (series, forecasts)."""
    grouped: dict[tuple[int, str], list[tuple[date, float]]] = {}
    for business, line, month, value in rows:
        grouped.setdefault((business, line), []).append((month, value))
    series = forecasts = 0
    for (business, line), values in sorted(grouped.items()):
        found = monthly_series(values, through)
        if found is None:
            continue
        first, y = found
        series += 1
        result = forecast_series(y)
        con.execute(
            "INSERT INTO ml.forecast_series VALUES (?, ?, ?, ?, ?, ?, ?)",
            [run_id, business, line, first, result.months, result.status, result.chosen],
        )
        for b in result.backtests:
            con.execute(
                "INSERT INTO ml.backtest VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    run_id,
                    business,
                    line,
                    b.model,
                    b.origins,
                    HORIZON,
                    b.mae,
                    b.mape,
                    b.mase,
                    b.model == result.chosen,
                ],
            )
        if result.status != "forecast":
            continue
        forecasts += 1
        for step, (f, lo, hi) in enumerate(
            zip(result.forecast, result.lower, result.upper, strict=True), start=1
        ):
            con.execute(
                "INSERT INTO ml.forecast VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [run_id, business, line, month_add(through, step), step, result.chosen, f, lo, hi],
            )
    return series, forecasts


def _write_scores(
    con: duckdb.DuckDBPyConnection, run_id: str, scores: list[anomalies.Score]
) -> None:
    for s in scores:
        # An infinite z (a history that never varied) is stored as null with the flag that says why.
        finite = math.isfinite(s.z)
        con.execute(
            "INSERT INTO ml.remittance_score VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                s.business_id,
                s.provider,
                s.month,
                s.measure,
                s.billed,
                s.amount,
                s.rate,
                s.usual_rate,
                s.spread,
                s.history_months,
                s.z if finite else None,
                not finite and s.z > 0,
                s.flagged,
            ],
        )
