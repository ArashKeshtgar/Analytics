"""Synthetic source -> extract -> warehouse -> dbt -> API, checked against hand-added numbers.

Expected values (see tests/synthetic_source.py), Harbourview (HV) and the lab (LAB):
  revenue = credits - debits on revenue accounts, by posting month, drafts left out
    HV Sep 100 + 50 = 150;  HV Oct 200 - 30 (refused) - 10 (short-paid) = 160;  LAB Oct 70
  OHIP, HV: Sep billed 100, paid 60, adjusted 30, outstanding 10;
            Oct billed 200, outstanding 200, refused 30 (15%), short-paid 10 (5%)
  ageing, receivable, HV: balances item1 10 (due Oct 10), item2 200 (due Nov 4), item3 50 (Oct 20)
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from analytics.api import create_app
from analytics.extract import extract_finance
from analytics.settings import Settings
from analytics.sources import DuckDbSource
from analytics.warehouse import build
from tests import synthetic_source
from tests.conftest import FakeClinicHub, make_settings


@pytest.fixture
def client(auth_settings: Settings, group_headers: dict[str, str]) -> TestClient:
    return TestClient(create_app(auth_settings), headers=group_headers)


def rows(client: TestClient, url: str, **params: Any) -> list[dict[str, Any]]:
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def test_revenue_by_month_all_businesses(client: TestClient) -> None:
    result = rows(client, "/api/finance/revenue")
    assert {r["month"]: r["revenue"] for r in result} == {"2026-09-01": 150.0, "2026-10-01": 230.0}


def test_draft_entry_is_not_revenue(client: TestClient) -> None:
    total = sum(r["revenue"] for r in rows(client, "/api/finance/revenue"))
    assert total == 380.0  # 999 of the draft is not in it


def test_revenue_for_a_clinic_by_slug_or_code(client: TestClient) -> None:
    by_slug = rows(client, "/api/finance/revenue", business="harbourview")
    by_code = rows(client, "/api/finance/revenue", business="hv")
    assert by_slug == by_code
    assert {r["month"]: r["revenue"] for r in by_slug} == {"2026-09-01": 150.0, "2026-10-01": 160.0}
    assert rows(client, "/api/finance/revenue", business="nobody") == []


def test_revenue_date_range(client: TestClient) -> None:
    result = rows(client, "/api/finance/revenue", **{"from": "2026-10-01", "to": "2026-10-31"})
    assert [r["revenue"] for r in result] == [230.0]


def test_revenue_by_line_of_business_and_provider(client: TestClient) -> None:
    lob = rows(client, "/api/finance/revenue", groupBy="lineOfBusiness", **{"from": "2026-10-01"})
    assert {r["line_of_business"]: r["revenue"] for r in lob} == {"Clinic": 160.0, "Lab": 70.0}
    provider = rows(client, "/api/finance/revenue", groupBy="provider", business="HV")
    assert {r["provider"]: r["revenue"] for r in provider} == {"123456": 300.0, "none": 10.0}
    both = rows(client, "/api/finance/revenue", groupBy="business,month")
    assert len(both) == 3


def test_revenue_rejects_unknown_group(client: TestClient) -> None:
    assert client.get("/api/finance/revenue", params={"groupBy": "patient"}).status_code == 422


def test_ohip_collection(client: TestClient) -> None:
    sep, octo = rows(client, "/api/finance/ohip-collection", business="HV")
    assert (sep["month"], sep["billed"], sep["paid"], sep["adjusted"], sep["outstanding"]) == (
        "2026-09-01",
        100.0,
        60.0,
        30.0,
        10.0,
    )
    assert (sep["short_paid"], sep["refused"]) == (0.0, 0.0)
    assert (octo["billed"], octo["outstanding"]) == (200.0, 200.0)
    assert (octo["short_paid"], octo["refused"]) == (10.0, 30.0)
    assert (octo["short_paid_rate"], octo["refused_rate"]) == (0.05, 0.15)


def test_aging_uses_the_latest_snapshot(client: TestClient) -> None:
    result = rows(client, "/api/finance/aging", business="HV")
    assert {r["snapshot_date"] for r in result} == {"2026-11-15"}
    by = {(r["party_type"], r["aging_bucket"]): r["balance"] for r in result}
    assert by == {("OHIP", "1-30"): 200.0, ("OHIP", "31-60"): 10.0, ("Patient", "1-30"): 50.0}


def test_aging_as_of_an_earlier_snapshot(client: TestClient) -> None:
    result = rows(client, "/api/finance/aging", business="HV", asOf="2026-11-01")
    assert {r["snapshot_date"] for r in result} == {"2026-10-31"}
    by = {(r["party_type"], r["aging_bucket"]): r["balance"] for r in result}
    assert by == {("OHIP", "current"): 200.0, ("OHIP", "1-30"): 10.0, ("Patient", "1-30"): 50.0}


def test_aging_payables(client: TestClient) -> None:
    result = rows(client, "/api/finance/aging", side="payable")
    assert [(r["party_type"], r["aging_bucket"], r["balance"]) for r in result] == [
        ("Supplier", "31-60", 40.0)
    ]


def test_warehouse_holds_no_contact_details_or_free_text(built: Settings) -> None:
    con = duckdb.connect(str(built.warehouse_path), read_only=True)
    columns = {
        r[0].lower()
        for r in con.execute(
            "select column_name from information_schema.columns "
            "where table_schema in ('raw', 'main')"
        ).fetchall()
    }
    assert not columns & {"email", "phone", "memo", "description", "createdby", "reference"}
    text = str(con.execute("select * from main.dim_party").fetchall())
    assert "example.test" not in text and "555-" not in text


def test_dim_business_has_clinic_slug(built: Settings) -> None:
    con = duckdb.connect(str(built.warehouse_path), read_only=True)
    got = dict(con.execute("select code, clinic_slug from main.dim_business").fetchall())
    assert got == {"HV": "harbourview", "LAB": None}


def test_unbalanced_entry_fails_the_build(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    extract_finance(
        DuckDbSource(synthetic_source.create(unbalanced_entry=True)),
        settings,
        now=datetime(2026, 10, 31, 12, tzinfo=UTC),
    )
    assert build(settings) != 0


def test_build_without_an_extract_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert build(make_settings(tmp_path)) == 1
    assert "analytics extract finance" in capsys.readouterr().err


def test_api_before_the_warehouse_exists(
    tmp_path: Path, clinichub: FakeClinicHub, group_headers: dict[str, str]
) -> None:
    settings = make_settings(tmp_path, oidc_jwks_uri=clinichub.jwks_uri)
    client = TestClient(create_app(settings), headers=group_headers)
    assert client.get("/api/finance/revenue").status_code == 503


def test_a_source_with_no_tax_codes_or_departments_still_builds(tmp_path: Path) -> None:
    """Parquet types an all-NULL column as null; staging casts it so the models do not guess integer."""
    con = synthetic_source.create()
    con.execute("UPDATE gl.JournalLine SET TaxCode = NULL, Department = NULL, ProviderCode = NULL")
    con.execute("UPDATE gl.Account SET Subtype = NULL, GifiCode = NULL")
    settings = make_settings(tmp_path)
    extract_finance(DuckDbSource(con), settings, now=datetime(2026, 10, 31, 12, tzinfo=UTC))
    assert build(settings) == 0
