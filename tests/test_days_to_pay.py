"""Days to pay, from the receipts FinancePowerApp posted (ar.vw_ItemPayments), an optional table."""

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import polars as pl
import pytest
from fastapi.testclient import TestClient

from analytics.api import create_app
from analytics.extract import extract_finance
from analytics.settings import Settings
from analytics.sources import DuckDbSource
from analytics.warehouse import build, complete_runs
from tests import synthetic_source
from tests.conftest import DASHBOARD, GROUP, ISSUER, FakeClinicHub, make_settings

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    settings = make_settings(tmp_path_factory.mktemp("dtp"))
    extract_finance(DuckDbSource(synthetic_source.create()), settings, now=NOW)
    assert build(settings) == 0
    return settings


def test_the_mart_is_the_amount_weighted_wait_per_payer_and_payment_month(built: Settings) -> None:
    con = duckdb.connect(str(built.warehouse_path), read_only=True)
    rows = con.execute(
        "select party_type, month::varchar, payments, amount, mean_days, max_days "
        "from main.mart_days_to_pay order by party_type, month"
    ).fetchall()
    # OHIP item of 09-10: 40 paid on 09-20 (10 days), 20 on 10-10 (30 days).
    # The patient's item of 09-20: 50 on 09-30.
    assert [(r[0], r[1], r[2], float(r[3]), float(r[4]), r[5]) for r in rows] == [
        ("OHIP", "2026-09-01", 1, 40.0, 10.0, 10),
        ("OHIP", "2026-10-01", 1, 20.0, 30.0, 30),
        ("Patient", "2026-09-01", 1, 50.0, 10.0, 10),
    ]


def client(settings: Settings, hub: FakeClinicHub, *permissions: str) -> TestClient:
    s = settings.model_copy(update={"oidc_issuer": ISSUER, "oidc_jwks_uri": hub.jwks_uri})
    token = hub.token(permission=list(permissions), clinic_slug="harbourview")
    return TestClient(create_app(s), headers={"Authorization": f"Bearer {token}"})


def test_the_api_filters_by_payer_and_scope(built: Settings, clinichub: FakeClinicHub) -> None:
    group = client(built, clinichub, GROUP)
    everything = group.get("/api/finance/days-to-pay").json()
    assert {(r["payer"], r["month"]) for r in everything} == {
        ("OHIP", "2026-09-01"),
        ("OHIP", "2026-10-01"),
        ("Patient", "2026-09-01"),
    }
    ohip = group.get(
        "/api/finance/days-to-pay", params={"payer": "OHIP", "from": "2026-10-01"}
    ).json()
    assert [(r["business"], r["month"], r["mean_days"], r["max_days"]) for r in ohip] == [
        ("HV", "2026-10-01", 30.0, 30)
    ]
    # a clinic user sees its own clinic's business only (all of this data is Harbourview's)
    own = client(built, clinichub, DASHBOARD).get("/api/finance/days-to-pay")
    assert own.status_code == 200 and {r["business"] for r in own.json()} <= {"HV"}


def test_a_source_without_the_view_still_extracts_and_builds_with_an_empty_mart(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    extract_finance(DuckDbSource(synthetic_source.create(payments=False)), settings, now=NOW)
    run_dir = settings.data_dir / "raw" / "finance" / "20261115T120000Z"
    assert sorted(p.stem for p in run_dir.glob("*.parquet")) == sorted(
        synthetic_source.table_names(payments=False)
    )
    assert complete_runs(settings) == [
        "20261115T120000Z"
    ]  # the optional table never makes a run incomplete
    assert build(settings) == 0
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    assert con.execute("select count(*) from main.mart_days_to_pay").fetchone() == (0,)


def test_an_extract_from_before_the_view_is_still_complete_and_the_latest_decides(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    old = datetime(2026, 11, 14, 12, tzinfo=UTC)
    extract_finance(DuckDbSource(synthetic_source.create(payments=False)), settings, now=old)
    extract_finance(DuckDbSource(synthetic_source.create()), settings, now=NOW)
    assert len(complete_runs(settings)) == 2
    assert build(settings) == 0
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    assert con.execute("select count(*) from main.mart_days_to_pay").fetchone() == (3,)
    paid = pl.read_parquet(
        settings.data_dir / "raw" / "finance" / "20261115T120000Z" / "ar_vw_itempayments.parquet"
    )
    assert set(paid.columns) == {"ItemId", "EntityId", "PaymentDate", "Amount"}
