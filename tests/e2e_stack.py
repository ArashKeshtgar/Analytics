"""The services the browser tests (web/e2e) run against: a fake ClinicHub sign-in on :5301 and the
Analytics API on :5600, over a warehouse built from the synthetic source. Run:
`uv run python -m tests.e2e_stack` (prints READY when both answer), stop with Ctrl-C.

The data is the synthetic source with the HST cases plus a year-earlier month, so that every page
has something to show. Numbers the browser tests expect are in web/e2e/dashboard.spec.ts.
"""

import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import uvicorn

from analytics.api import create_app
from analytics.extract import extract_finance
from analytics.settings import Settings
from analytics.sources import DuckDbSource
from analytics.warehouse import build
from tests import synthetic_source
from tests.fake_idp import FakeIdP


def add_prior_year(con: duckdb.DuckDBPyConnection) -> None:
    """October 2025: Harbourview clinic revenue 90 and the lab 60 (both EXEMPT)."""
    con.execute("""
        INSERT INTO dbo.AccountingPeriods VALUES (3, 2025, 10, true, '2025-11-01');
        INSERT INTO gl.JournalEntry (JournalEntryId, EntityId, Number, EntryDate, PeriodId, Source,
                                     "Status", LatePosting) VALUES
          (13, 1, 'JE13', '2025-10-10', 3, 'clinichub', 'Posted', false),
          (14, 2, 'JE14', '2025-10-05', 3, 'labflow', 'Posted', false);
        INSERT INTO gl.JournalLine (JournalLineId, JournalEntryId, LineNumber, AccountId, Debit, Credit,
                                    PartyId, Department, ProviderCode, TaxCode) VALUES
          (25, 13, 1, 2, 90, 0, 1, 'Clinic', NULL, NULL),
          (26, 13, 2, 3, 0, 90, NULL, 'Clinic', '123456', 'EXEMPT'),
          (27, 14, 1, 2, 60, 0, 2, 'Lab', NULL, NULL),
          (28, 14, 2, 4, 0, 60, NULL, 'Lab', NULL, 'EXEMPT');
    """)


def build_warehouse(root: Path) -> Settings:
    settings = Settings(
        data_dir=root / "data",
        warehouse_path=root / "data" / "warehouse.duckdb",
        dbt_project_dir=Path("dbt"),
        _env_file=None,  # type: ignore[call-arg]
    )
    for day in (datetime(2026, 10, 31, 12, tzinfo=UTC), datetime(2026, 11, 15, 12, tzinfo=UTC)):
        con = synthetic_source.create(tax_entries=True)
        add_prior_year(con)
        extract_finance(DuckDbSource(con), settings, now=day)
    if build(settings) != 0:
        raise SystemExit("the warehouse did not build")
    return settings


def main() -> None:
    idp = FakeIdP(port=5301)
    idp.start()
    root = Path(tempfile.mkdtemp(prefix="analytics-e2e-"))
    settings = build_warehouse(root).model_copy(
        update={"oidc_issuer": idp.issuer, "oidc_jwks_uri": idp.jwks_uri}
    )
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=5600, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    print("READY", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
