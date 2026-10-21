"""The endpoints the dashboard needs, against hand-added numbers.

Base data (tests/synthetic_source.py), Harbourview HV and the lab:
  OHIP by provider (journal): provider 123456 billed Sep 100, Oct 200 = 300, nothing refused;
    "none" (the adjustment lines carry no provider) billed 0, short-paid 10, refused 30.
Tax data (create(tax_entries=True)): see _add_tax_entries.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from analytics.api import create_app
from analytics.settings import Settings
from tests.conftest import DASHBOARD, GROUP, FakeClinicHub


@pytest.fixture
def group(auth_settings: Settings, group_headers: dict[str, str]) -> TestClient:
    return TestClient(create_app(auth_settings), headers=group_headers)


@pytest.fixture
def group_tax(auth_settings_tax: Settings, group_headers: dict[str, str]) -> TestClient:
    return TestClient(create_app(auth_settings_tax), headers=group_headers)


def clinic(settings: Settings, hub: FakeClinicHub, slug: str = "harbourview") -> TestClient:
    token = hub.token(permission=[DASHBOARD], clinic_slug=slug)
    return TestClient(create_app(settings), headers={"Authorization": f"Bearer {token}"})


def get(client: TestClient, url: str, **params: Any) -> Any:
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---- businesses and range -----------------------------------------------------------------------


def test_businesses_for_a_group_viewer(group: TestClient) -> None:
    result = get(group, "/api/finance/businesses")
    assert [(b["code"], b["kind"], b["clinicSlug"]) for b in result] == [
        ("HV", "Clinic", "harbourview"),
        ("LAB", "Lab", None),
    ]


def test_a_clinic_viewer_sees_only_their_business(
    auth_settings: Settings, clinichub: FakeClinicHub
) -> None:
    result = get(clinic(auth_settings, clinichub), "/api/finance/businesses")
    assert [b["code"] for b in result] == ["HV"]
    assert get(clinic(auth_settings, clinichub, "lakeshore"), "/api/finance/businesses") == []


def test_range_is_the_first_and_last_month_with_revenue(
    group: TestClient, auth_settings: Settings, clinichub: FakeClinicHub
) -> None:
    assert get(group, "/api/finance/range") == {
        "firstMonth": "2026-09-01",
        "lastMonth": "2026-10-01",
    }
    assert get(group, "/api/finance/range", business="LAB") == {
        "firstMonth": "2026-10-01",
        "lastMonth": "2026-10-01",
    }
    nobody = get(clinic(auth_settings, clinichub, "lakeshore"), "/api/finance/range")
    assert nobody == {"firstMonth": None, "lastMonth": None}


# ---- OHIP by provider ---------------------------------------------------------------------------


def test_ohip_by_provider(group: TestClient) -> None:
    result = get(group, "/api/finance/ohip-providers")
    assert result == [
        {
            "provider": "123456",
            "billed": 300.0,
            "short_paid": 0.0,
            "refused": 0.0,
            "short_paid_rate": 0.0,
            "refused_rate": 0.0,
        },
        {
            "provider": "none",
            "billed": 0.0,
            "short_paid": 10.0,
            "refused": 30.0,
            "short_paid_rate": None,
            "refused_rate": None,
        },
    ]


def test_ohip_by_provider_in_a_range_and_for_one_business(group: TestClient) -> None:
    october = get(group, "/api/finance/ohip-providers", **{"from": "2026-10-01"})
    assert {r["provider"]: r["billed"] for r in october} == {"123456": 200.0, "none": 0.0}
    assert get(group, "/api/finance/ohip-providers", business="LAB") == []


def test_ohip_by_provider_is_clinic_scoped(
    auth_settings: Settings, clinichub: FakeClinicHub
) -> None:
    mine = get(clinic(auth_settings, clinichub), "/api/finance/ohip-providers")
    assert [r["provider"] for r in mine] == ["123456", "none"]
    assert get(clinic(auth_settings, clinichub, "lakeshore"), "/api/finance/ohip-providers") == []


# ---- HST ----------------------------------------------------------------------------------------


def by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], float]:
    return {(r["month"], r["measure"], r["taxCode"]): r["amount"] for r in rows}


def test_hst_by_month_tax_code_and_measure(group_tax: TestClient) -> None:
    got = by_key(get(group_tax, "/api/finance/hst"))
    assert got == {
        ("2026-09-01", "sales", "EXEMPT"): 150.0,
        ("2026-09-01", "sales", "HST13"): 100.0,
        ("2026-09-01", "tax_collected", "HST13"): 13.0,
        ("2026-10-01", "sales", "EXEMPT"): 270.0,  # HV 200 + lab 70
        ("2026-10-01", "sales", "ZERO"): 40.0,
        ("2026-10-01", "sales", "(none)"): -40.0,
        ("2026-10-01", "purchases", "HST13"): 200.0,
        ("2026-10-01", "itc", "HST13"): 26.0,
    }


def test_hst_carries_the_tax_code_name_and_rate(group_tax: TestClient) -> None:
    rows = get(group_tax, "/api/finance/hst", **{"from": "2026-09-01", "to": "2026-09-30"})
    hst13 = next(r for r in rows if r["taxCode"] == "HST13" and r["measure"] == "sales")
    assert (hst13["taxName"], hst13["ratePercent"]) == ("HST 13%", 13.0)
    none = get(group_tax, "/api/finance/hst", **{"from": "2026-10-01"})
    assert next(r for r in none if r["taxCode"] == "(none)")["taxName"] is None


def test_hst_for_one_business_and_for_a_clinic_viewer(
    group_tax: TestClient, auth_settings_tax: Settings, clinichub: FakeClinicHub
) -> None:
    lab = by_key(get(group_tax, "/api/finance/hst", business="LAB"))
    assert lab == {("2026-10-01", "sales", "EXEMPT"): 70.0}
    mine = by_key(get(clinic(auth_settings_tax, clinichub), "/api/finance/hst"))
    assert mine[("2026-10-01", "sales", "EXEMPT")] == 200.0
    assert get(clinic(auth_settings_tax, clinichub, "lakeshore"), "/api/finance/hst") == []


# ---- who may call -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "/api/finance/businesses",
        "/api/finance/range",
        "/api/finance/ohip-providers",
        "/api/finance/hst",
    ],
)
def test_the_new_endpoints_need_a_finance_permission(
    auth_settings: Settings, clinichub: FakeClinicHub, url: str
) -> None:
    client = TestClient(create_app(auth_settings))
    assert client.get(url).status_code == 401
    token = clinichub.token(permission=["analytics:models.view"])
    assert client.get(url, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    group_token = clinichub.token(permission=[GROUP])
    assert client.get(url, headers={"Authorization": f"Bearer {group_token}"}).status_code == 200
