"""A warehouse with only what `analytics score` reads (two revenue marts and the businesses),
built by hand with synthetic numbers, so the forecasts can be tested on years of history quickly.

- Harbourview (clinic, slug harbourview): line Clinic, 48 months Oct 2022 to Sep 2026 with a season
  and a trend; line Pharmacy, 10 months (too short). Provider 123456: 1-2% short-paid, then 10% in
  Sep 2026. Provider 654321: steady.
- Lakeshore (clinic, slug lakeshore): line Clinic, 30 months.
- A revenue row in Oct 2026, the month of the extract: not finished, never used.
"""

from datetime import date
from pathlib import Path

import duckdb
import numpy as np

from analytics.forecast import month_add

PATTERN = [1.1, 1.05, 1.0, 0.95, 0.9, 0.8, 0.75, 0.8, 1.0, 1.05, 1.1, 0.95]
AS_OF = date(2026, 10, 15)  # the extract's day; data through Sep 2026
THROUGH = date(2026, 9, 1)


def revenue(first: date, months: int, base: float, trend: float, seed: int) -> list[tuple]:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(months):
        m = month_add(first, i)
        value = base * PATTERN[(m.month - 1) % 12] + trend * i + rng.normal(0, base * 0.01)
        rows.append((m, round(float(value), 2)))
    return rows


def create(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("CREATE SCHEMA IF NOT EXISTS main")
    con.execute(
        "CREATE TABLE main.dim_business (business_id integer, code varchar, name varchar, "
        "kind varchar, clinic_slug varchar)"
    )
    con.execute(
        "INSERT INTO main.dim_business VALUES (1, 'HV', 'Harbourview', 'Clinic', 'harbourview'), "
        "(2, 'LS', 'Lakeshore', 'Clinic', 'lakeshore')"
    )
    con.execute(
        "CREATE TABLE main.mart_revenue_monthly (business_id integer, line_of_business varchar, "
        "provider_code varchar, month date, revenue decimal(14, 2), entries bigint)"
    )
    series = [
        (1, "Clinic", revenue(date(2022, 10, 1), 48, 20_000, 150, 1)),
        (1, "Pharmacy", revenue(date(2025, 12, 1), 10, 3_000, 0, 2)),
        (2, "Clinic", revenue(date(2024, 4, 1), 30, 8_000, 40, 3)),
    ]
    for business, line, rows in series:
        for m, v in rows:
            # Two providers per month, so the forecast has to add them up.
            con.execute(
                "INSERT INTO main.mart_revenue_monthly VALUES "
                "(?, ?, 'A', ?, ?, 1), (?, ?, 'B', ?, ?, 1)",
                [business, line, m, v * 0.6, business, line, m, v * 0.4],
            )
    con.execute(
        "INSERT INTO main.mart_revenue_monthly VALUES (1, 'Clinic', 'A', DATE '2026-10-01', 1, 1)"
    )
    con.execute(
        "CREATE TABLE main.mart_ohip_provider_monthly (business_id integer, provider_code varchar, "
        "month date, billed decimal(14, 2), short_paid decimal(14, 2), refused decimal(14, 2))"
    )
    rates = [0.01, 0.015, 0.012, 0.02, 0.011, 0.014, 0.013, 0.012, 0.10]
    for i, rate in enumerate(rates):
        m = month_add(date(2026, 1, 1), i)
        con.execute(
            "INSERT INTO main.mart_ohip_provider_monthly VALUES (1, '123456', ?, 10000, ?, 0), "
            "(1, '654321', ?, 8000, 80, 16)",
            [m, rate * 10_000, m],
        )
    # The unfinished month: a huge refusal that must not be scored yet.
    con.execute(
        "INSERT INTO main.mart_ohip_provider_monthly VALUES "
        "(1, '654321', DATE '2026-10-01', 8000, 80, 4000)"
    )
    con.close()
