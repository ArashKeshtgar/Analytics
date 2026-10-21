"""LabFlow's warehouse as a second source: monthly totals only, in mart_lab_volume_monthly."""

from pathlib import Path

import duckdb
import polars as pl
import pytest
from fastapi.testclient import TestClient

from analytics.api import create_app
from analytics.extract import extract_finance
from analytics.labflow_dw import dw_dir, extract_labflow_dw
from analytics.pipeline import run
from analytics.settings import Settings
from analytics.sources import DuckDbSource
from analytics.warehouse import build
from tests import synthetic_source
from tests.conftest import DASHBOARD, GROUP, ISSUER, FakeClinicHub, make_settings
from tests.test_run import DAY


def lab_warehouse() -> duckdb.DuckDBPyConnection:
    """The two objects LabFlow's login may read, shaped like them, with columns it must not take."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA dw")
    con.execute("""
        CREATE TABLE dw.vw_AnalyticsMonthly ("Year" smallint, "Month" tinyint, TestKey int,
            PayerType varchar, Results int, Visits int, Answered int, Abnormal int, Critical int,
            TurnaroundDaysSum int, TurnaroundCount int);
        INSERT INTO dw.vw_AnalyticsMonthly VALUES
          (2022, 3, 1, 'Insured', 10, 9, 10, 2, 0, 20, 10),
          (2022, 3, 1, 'Self-pay', 5, 5, 4, 1, 1, 0, 0),
          (2022, 4, 1, 'Insured', 6, 6, 6, 0, 0, 12, 4),
          (2022, 4, 2, 'Insured', 3, 3, 3, 3, 0, 9, 3);
        CREATE TABLE dw.DimTest (TestKey int, LegacyName varchar, LoincCode varchar,
            LabFlowCode varchar, TestName varchar, Section tinyint, IsPanel boolean,
            LegacyCode varchar);
        INSERT INTO dw.DimTest VALUES
          (1, 'legacy name, not to take', '14771-0', 'GLU-F', 'Glucose, fasting', 1, false, 'X1'),
          (2, 'legacy name, not to take', NULL, NULL, 'Ferritin', 2, false, 'X2');
    """)
    return con


@pytest.fixture(scope="module")
def built_dw(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    settings = make_settings(tmp_path_factory.mktemp("dw"))
    extract_finance(DuckDbSource(synthetic_source.create()), settings, now=DAY)
    extract_labflow_dw(DuckDbSource(lab_warehouse()), settings)
    assert build(settings) == 0
    return settings


def test_only_the_listed_columns_are_taken(built_dw: Settings) -> None:
    tests = pl.read_parquet(dw_dir(built_dw) / "dw_dimtest.parquet")
    assert tests.columns == [
        "TestKey",
        "LoincCode",
        "LabFlowCode",
        "TestName",
        "Section",
        "IsPanel",
    ]


def test_the_mart_has_a_row_per_month_test_and_payer_with_names(built_dw: Settings) -> None:
    con = duckdb.connect(str(built_dw.warehouse_path), read_only=True)
    rows = con.execute(
        "select month::varchar, test_name, loinc_code, payer_type, results, turnaround_mean_days "
        "from main.mart_lab_volume_monthly order by 1, 2, 4"
    ).fetchall()
    assert rows == [
        ("2022-03-01", "Glucose, fasting", "14771-0", "Insured", 10, 2.0),
        ("2022-03-01", "Glucose, fasting", "14771-0", "Self-pay", 5, None),
        ("2022-04-01", "Ferritin", None, "Insured", 3, 3.0),
        ("2022-04-01", "Glucose, fasting", "14771-0", "Insured", 6, 3.0),
    ]


def client(settings: Settings, hub: FakeClinicHub, *permissions: str) -> TestClient:
    s = settings.model_copy(update={"oidc_issuer": ISSUER, "oidc_jwks_uri": hub.jwks_uri})
    token = hub.token(permission=list(permissions), clinic_slug="harbourview")
    return TestClient(create_app(s), headers={"Authorization": f"Bearer {token}"})


def test_the_api_groups_by_month_test_or_payer_for_group_users(
    built_dw: Settings, clinichub: FakeClinicHub
) -> None:
    api = client(built_dw, clinichub, GROUP)
    months = api.get("/api/operations/lab-volumes").json()
    assert [(m["month"], m["results"], m["visits"], m["abnormal"]) for m in months] == [
        ("2022-03-01", 15, 14, 3),
        ("2022-04-01", 9, 9, 3),
    ]
    # March: 20 days over 10 results with a time; the self-pay ones had none
    assert months[0]["turnaround_mean_days"] == 2.0
    tests = api.get("/api/operations/lab-volumes", params={"groupBy": "test"}).json()
    assert [(t["test_name"], t["results"], t["turnaround_mean_days"]) for t in tests] == [
        ("Glucose, fasting", 21, 2.29),
        ("Ferritin", 3, 3.0),
    ]
    payers = api.get("/api/operations/lab-volumes", params={"groupBy": "payer"}).json()
    assert {p["payer_type"]: p["critical"] for p in payers} == {"Insured": 0, "Self-pay": 1}
    assert api.get("/api/operations/lab-volumes", params={"groupBy": "patient"}).status_code == 422


def test_a_clinic_user_is_refused(built_dw: Settings, clinichub: FakeClinicHub) -> None:
    response = client(built_dw, clinichub, DASHBOARD).get("/api/operations/lab-volumes")
    assert response.status_code == 403


def test_without_the_source_the_mart_is_empty(tmp_path: Path, clinichub: FakeClinicHub) -> None:
    settings = make_settings(tmp_path)
    extract_finance(DuckDbSource(synthetic_source.create()), settings, now=DAY)
    assert build(settings) == 0
    assert client(settings, clinichub, GROUP).get("/api/operations/lab-volumes").json() == []


def test_a_run_reads_it_and_a_failure_of_it_does_not_stop_the_run(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    finance = DuckDbSource(synthetic_source.create())
    lab = DuckDbSource(lab_warehouse())
    first = run(
        settings,
        now=DAY,
        extractor=lambda s: extract_finance(finance, s, now=DAY).rows,
        dw_extractor=lambda s: extract_labflow_dw(lab, s),
    )
    step = next(s for s in first.steps if s.name == "labflow")
    assert step.status == "ok" and step.detail.startswith("2 tables, 6 rows"), step.detail

    def down(s: Settings) -> dict[str, int]:
        raise ConnectionError("LabFlow's server did not answer")

    later = DAY.replace(hour=18)
    second = run(
        settings,
        now=later,
        extractor=lambda s: extract_finance(finance, s, now=later).rows,
        dw_extractor=down,
    )
    assert next(s for s in second.steps if s.name == "labflow").status == "failed"
    assert second.warehouse_replaced and second.status == "warning"
    con = duckdb.connect(str(settings.warehouse_path), read_only=True)
    # the last extract of it is built again
    assert con.execute("select sum(results) from main.mart_lab_volume_monthly").fetchone() == (24,)
