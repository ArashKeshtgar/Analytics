"""Analytics' figures against FinancePowerApp's own report views, after every run's build."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb

from analytics.extract import extract_finance
from analytics.pipeline import run
from analytics.reconcile import Reconciliation, compare, reconcile
from analytics.settings import Settings
from analytics.sources import DuckDbSource
from tests import synthetic_source
from tests.conftest import make_settings
from tests.test_run import DAY


def run_against(settings: Settings, books: duckdb.DuckDBPyConnection, **kw: object):  # type: ignore[no-untyped-def]
    """A run whose extract and reconciliation both read the same FinancePowerApp-shaped database."""
    source = DuckDbSource(books)
    return run(
        settings,
        now=DAY,
        extractor=lambda s: extract_finance(source, s, now=DAY).rows,
        reconciler=lambda s: reconcile(source, s.warehouse_path),
        **kw,  # type: ignore[arg-type]
    )


def test_the_marts_agree_with_the_books(tmp_path: Path) -> None:
    report = run_against(make_settings(tmp_path), synthetic_source.create(tax_entries=True))
    step = next(s for s in report.steps if s.name == "reconcile")
    assert step.status == "ok" and step.detail.endswith("0 differ"), step.detail
    assert report.status == "ok" and not [c for c in report.checks if c.kind == "reconcile"]
    # revenue, tax collected and ITCs per business and month, and both balances, were compared
    assert int(step.detail.split()[0]) >= 10


def test_books_that_moved_after_the_extract_are_reported_not_fatal(tmp_path: Path) -> None:
    books = synthetic_source.create()
    settings = make_settings(tmp_path)
    source = DuckDbSource(books)

    def extract_then_post(s: Settings) -> dict[str, int]:
        rows = extract_finance(source, s, now=DAY).rows
        # Posted in FinancePowerApp a moment after the extract: 25 more OHIP revenue in October.
        books.execute(
            "INSERT INTO gl.JournalEntry (JournalEntryId, EntityId, Number, EntryDate, PeriodId, "
            'Source, "Status", LatePosting) '
            "VALUES (9, 1, 'JE9', '2026-10-21', 2, 'clinichub', 'Posted', false)"
        )
        books.execute(
            "INSERT INTO gl.JournalLine "
            "(JournalLineId, JournalEntryId, LineNumber, AccountId, Debit, Credit) "
            "VALUES (20, 9, 1, 2, 25, 0), (21, 9, 2, 3, 0, 25)"
        )
        books.execute("UPDATE ar.Item SET Balance = Balance + 25 WHERE ItemId = 2")
        return rows

    report = run(
        settings,
        now=DAY,
        extractor=extract_then_post,
        reconciler=lambda s: reconcile(source, s.warehouse_path),
    )
    assert report.warehouse_replaced and report.status == "warning"
    found = {(c.subject, c.message) for c in report.checks if c.kind == "reconcile"}
    assert found == {
        # 200 OHIP less 30 refused and 10 short-paid, then the 25 posted after the extract
        ("revenue business 1 2026-10", "FinancePowerApp 185.00, Analytics 160.00"),
        ("receivable business 1", "FinancePowerApp 285.00, Analytics 260.00"),
        # the same 25 on the trial balance: a debit on receivables, a credit on OHIP revenue
        ("trial_balance 1100 business 1", "FinancePowerApp 335.00, Analytics 310.00"),
        ("trial_balance 4000 business 1", "FinancePowerApp -325.00, Analytics -300.00"),
    }
    assert all(c.level == "warning" for c in report.checks if c.kind == "reconcile")


def test_a_reconciliation_that_cannot_run_is_an_error_but_the_data_still_goes_in(
    tmp_path: Path,
) -> None:
    def refused(s: Settings) -> Reconciliation:
        raise PermissionError("The SELECT permission was denied on the object 'vw_HstReturn'")

    books = DuckDbSource(synthetic_source.create())
    report = run(
        make_settings(tmp_path),
        now=DAY,
        extractor=lambda s: extract_finance(books, s, now=DAY).rows,
        reconciler=refused,
    )
    step = next(s for s in report.steps if s.name == "reconcile")
    assert step.status == "failed" and "PermissionError" in step.detail
    assert report.warehouse_replaced and report.status == "warning"
    assert [c.subject for c in report.checks if c.level == "error"] == ["reconcile"]


def test_without_books_read_in_this_run_it_is_skipped(tmp_path: Path) -> None:
    books = DuckDbSource(synthetic_source.create())
    report = run(
        make_settings(tmp_path),
        now=DAY,
        extractor=lambda s: extract_finance(books, s, now=DAY).rows,
    )
    step = next(s for s in report.steps if s.name == "reconcile")
    assert step.status == "skipped"


def test_a_figure_on_one_side_only_counts_as_zero_on_the_other() -> None:
    oct_ = date(2026, 10, 1)
    result = compare(
        {("revenue", 1, oct_): Decimal("10.00"), ("itc", 1, oct_): Decimal("0.004")},
        {("revenue", 2, oct_): Decimal("5.00"), ("itc", 1, oct_): Decimal("0.00")},
    )
    assert result.compared == 3
    assert [(d.subject(), d.books, d.analytics) for d in result.differences] == [
        ("revenue business 1 2026-10", Decimal("10.00"), Decimal("0.00")),
        ("revenue business 2 2026-10", Decimal("0.00"), Decimal("5.00")),
    ]
