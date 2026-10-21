"""Analytics' figures against FinancePowerApp's own (phase 3's open item, built in phase 6).

After the build, a run asks FinancePowerApp for the same totals through its own report views and
compares them with the marts, figure by figure:

- revenue per business and posting month: `gl.vw_PeriodMovement` on revenue accounts (credits minus
  debits) against `mart_revenue_monthly`;
- HST collected and input tax credits per business and posting month: `tax.vw_HstReturn` lines 103
  and 106 against `mart_hst_period`;
- what is owed to and by each business: `ar.Item` / `ap.Item` balances against the latest
  snapshot in `fact_open_item_snapshot`;
- the trial balance: per business and account, debits minus credits of every posted entry
  (`gl.vw_PeriodMovement`, the view FinancePowerApp's own trial-balance report is built from)
  against `fact_gl_line`. One figure per account, named `trial_balance {account number}`.

The two views are the only ones the read-only login may read (they carry no text). A figure on one
side only counts as zero on the other. A difference is a warning, not a failed run: the books can
move between the extract and these queries, a few seconds apart.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from analytics.settings import Settings
from analytics.sources import Source, SqlServerSource

TOLERANCE = Decimal("0.005")

# Written for SQL Server and DuckDB both (the tests use a DuckDB copy of the schema).
BOOKS: dict[str, str] = {
    "revenue": """
        SELECT pm.EntityId AS business_id, p."Year" AS yr, p."Month" AS mo, -SUM(pm.Net) AS amount
        FROM gl.vw_PeriodMovement pm
        JOIN gl.Account a ON a.AccountId = pm.AccountId
        JOIN dbo.AccountingPeriods p ON p.PeriodId = pm.PeriodId
        WHERE a."Type" = 'Revenue'
        GROUP BY pm.EntityId, p."Year", p."Month"
    """,
    "tax_collected": """
        SELECT h.EntityId AS business_id, p."Year" AS yr, p."Month" AS mo,
               SUM(h.Line103TaxCollected) AS amount
        FROM tax.vw_HstReturn h JOIN dbo.AccountingPeriods p ON p.PeriodId = h.PeriodId
        GROUP BY h.EntityId, p."Year", p."Month"
    """,
    "itc": """
        SELECT h.EntityId AS business_id, p."Year" AS yr, p."Month" AS mo,
               SUM(h.Line106InputTaxCredits) AS amount
        FROM tax.vw_HstReturn h JOIN dbo.AccountingPeriods p ON p.PeriodId = h.PeriodId
        GROUP BY h.EntityId, p."Year", p."Month"
    """,
    "receivable": """
        SELECT EntityId AS business_id, NULL AS yr, NULL AS mo, SUM(Balance) AS amount
        FROM ar.Item GROUP BY EntityId
    """,
    "payable": """
        SELECT EntityId AS business_id, NULL AS yr, NULL AS mo, SUM(Balance) AS amount
        FROM ap.Item GROUP BY EntityId
    """,
    "trial_balance": """
        SELECT pm.EntityId AS business_id, NULL AS yr, NULL AS mo, SUM(pm.Net) AS amount,
               a.Number AS account
        FROM gl.vw_PeriodMovement pm JOIN gl.Account a ON a.AccountId = pm.AccountId
        GROUP BY pm.EntityId, a.Number
    """,
}

WAREHOUSE: dict[str, str] = {
    "revenue": """
        select business_id, year(month) as yr, month(month) as mo, sum(revenue) as amount
        from main.mart_revenue_monthly group by 1, 2, 3
    """,
    "tax_collected": """
        select business_id, year(month), month(month), sum(amount)
        from main.mart_hst_period where measure = 'tax_collected' group by 1, 2, 3
    """,
    "itc": """
        select business_id, year(month), month(month), sum(amount)
        from main.mart_hst_period where measure = 'itc' group by 1, 2, 3
    """,
    "receivable": """
        select business_id, null, null, sum(balance) from main.fact_open_item_snapshot
        where side = 'receivable'
          and snapshot_date = (select max(snapshot_date) from main.fact_open_item_snapshot)
        group by 1
    """,
    "payable": """
        select business_id, null, null, sum(balance) from main.fact_open_item_snapshot
        where side = 'payable'
          and snapshot_date = (select max(snapshot_date) from main.fact_open_item_snapshot)
        group by 1
    """,
    "trial_balance": """
        select f.business_id, null, null, sum(f.debit - f.credit), a.number
        from main.fact_gl_line f join main.dim_account a using (account_id)
        group by 1, 5
    """,
}

Key = tuple[str, int, date | None]


@dataclass
class Difference:
    measure: str
    business_id: int
    month: date | None  # None for a balance
    books: Decimal
    analytics: Decimal

    def subject(self) -> str:
        when = f" {self.month:%Y-%m}" if self.month else ""
        return f"{self.measure} business {self.business_id}{when}"

    def message(self) -> str:
        return f"FinancePowerApp {self.books}, Analytics {self.analytics}"


@dataclass
class Reconciliation:
    compared: int = 0
    differences: list[Difference] = field(default_factory=list)

    def describe(self) -> str:
        return f"{self.compared} figures compared, {len(self.differences)} differ"


Reconciler = Callable[[Settings], Reconciliation]


def _amount(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01")) if value is not None else Decimal("0.00")


def _key(measure: str, business: object, yr: object, mo: object) -> Key:
    month = date(int(str(yr)), int(str(mo)), 1) if yr is not None and mo is not None else None
    return (measure, int(str(business)), month)


def _name(measure: str, account: list[object]) -> str:
    """A figure per account is named after it: `trial_balance 4000`."""
    return f"{measure} {account[0]}" if account else measure


def books_figures(source: Source) -> dict[Key, Decimal]:
    figures: dict[Key, Decimal] = {}
    for measure, sql in BOOKS.items():
        for business, yr, mo, amount, *account in source.read(sql).iter_rows():
            figures[_key(_name(measure, account), business, yr, mo)] = _amount(amount)
    return figures


def warehouse_figures(path: Path) -> dict[Key, Decimal]:
    con = duckdb.connect(str(path), read_only=True)
    try:
        figures: dict[Key, Decimal] = {}
        for measure, sql in WAREHOUSE.items():
            for business, yr, mo, amount, *account in con.execute(sql).fetchall():
                figures[_key(_name(measure, account), business, yr, mo)] = _amount(amount)
        return figures
    finally:
        con.close()


def compare(books: dict[Key, Decimal], analytics: dict[Key, Decimal]) -> Reconciliation:
    result = Reconciliation()
    for key in sorted(
        books.keys() | analytics.keys(), key=lambda k: (k[0], k[1], k[2] or date.min)
    ):
        b, a = books.get(key, Decimal("0.00")), analytics.get(key, Decimal("0.00"))
        result.compared += 1
        if abs(b - a) > TOLERANCE:
            result.differences.append(Difference(key[0], key[1], key[2], b, a))
    return result


def reconcile(source: Source, warehouse: Path) -> Reconciliation:
    return compare(books_figures(source), warehouse_figures(warehouse))


def sql_server_reconcile(settings: Settings) -> Reconciliation:
    source = SqlServerSource(settings.finance_connection_string)
    try:
        return reconcile(source, settings.warehouse_path)
    finally:
        source.close()
