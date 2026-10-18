"""The forecast and anomaly endpoints over a scored warehouse (tests/ml_warehouse.py)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from analytics.api import create_app
from analytics.forecast import BASELINE
from analytics.scoring import score
from tests import ml_warehouse
from tests.conftest import DASHBOARD, GROUP, ISSUER, MODELS, FakeClinicHub, make_settings


def client_for(root: Path, clinichub: FakeClinicHub, scored: bool) -> TestClient:
    settings = make_settings(root).model_copy(
        update={"oidc_issuer": ISSUER, "oidc_jwks_uri": clinichub.jwks_uri}
    )
    ml_warehouse.create(settings.warehouse_path)
    if scored:
        score(settings, as_of=ml_warehouse.AS_OF, now=datetime(2026, 10, 16, 3, tzinfo=UTC))
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def api(tmp_path_factory: pytest.TempPathFactory, clinichub: FakeClinicHub) -> TestClient:
    return client_for(tmp_path_factory.mktemp("models_api"), clinichub, scored=True)


def auth(clinichub: FakeClinicHub, *permission: str, clinic: str | None = None) -> dict[str, str]:
    token = clinichub.token(permission=list(permission), clinic_slug=clinic)
    return {"Authorization": "Bearer " + token}


def test_forecasts_need_the_models_permission(api: TestClient, clinichub: FakeClinicHub) -> None:
    url = "/api/models/revenue-forecast"
    assert api.get(url).status_code == 401
    assert api.get(url, headers=auth(clinichub, GROUP)).status_code == 403
    assert api.get(url, headers=auth(clinichub, DASHBOARD, clinic="harbourview")).status_code == 403
    # models.view alone sees no business: the business scope still comes from the other two.
    assert api.get(url, headers=auth(clinichub, MODELS)).status_code == 403
    assert api.get(url, headers=auth(clinichub, GROUP, MODELS)).status_code == 200


def test_the_group_sees_every_series_with_its_backtests_and_forecast(
    api: TestClient, clinichub: FakeClinicHub
) -> None:
    body = api.get("/api/models/revenue-forecast", headers=auth(clinichub, GROUP, MODELS)).json()
    assert body["run"]["dataThrough"] == "2026-09-01"
    keys = [(s["business"], s["line_of_business"], s["status"]) for s in body["series"]]
    assert keys == [
        ("HV", "Clinic", "forecast"),
        ("HV", "Pharmacy", "too-short"),
        ("LS", "Clinic", "forecast"),
    ]
    hv = body["series"][0]
    assert hv["business_name"] == "Harbourview" and hv["months"] == 48
    assert {b["model"] for b in hv["backtests"]} == {BASELINE, "ets", "sarima", "gradient-boosting"}
    assert [b["model"] for b in hv["backtests"] if b["chosen"]] == [hv["model"]]
    assert len(hv["history"]) == 48 and hv["history"][-1]["month"] == "2026-09-01"
    assert [f["month"] for f in hv["forecast"]][0] == "2026-10-01" and len(hv["forecast"]) == 6
    assert all(f["lower"] <= f["forecast"] <= f["upper"] for f in hv["forecast"])
    short = body["series"][1]
    assert short["model"] is None and short["backtests"] == [] and short["forecast"] == []
    assert len(short["history"]) == 10


def test_a_clinic_sees_only_its_own_series(api: TestClient, clinichub: FakeClinicHub) -> None:
    headers = auth(clinichub, DASHBOARD, MODELS, clinic="harbourview")
    body = api.get("/api/models/revenue-forecast", headers=headers).json()
    assert {s["business"] for s in body["series"]} == {"HV"}
    other = api.get("/api/models/revenue-forecast?business=LS", headers=headers).json()
    assert other["series"] == []


def test_anomalies_come_with_the_numbers_behind_them(
    api: TestClient, clinichub: FakeClinicHub
) -> None:
    rows = api.get(
        "/api/finance/ohip-anomalies", headers=auth(clinichub, DASHBOARD, clinic="harbourview")
    ).json()
    assert rows == [
        {
            "business": "HV",
            "provider": "123456",
            "month": "2026-09-01",
            "measure": "short_paid",
            "billed": 10000.0,
            "amount": 1000.0,
            "rate": 0.1,
            "usual_rate": 0.0125,
            "spread": pytest.approx(0.0015, abs=1e-4),
            "z": pytest.approx(39.3, abs=0.1),
            "above_steady_history": False,
            "history_months": 8,
        }
    ]
    lakeshore = auth(clinichub, DASHBOARD, clinic="lakeshore")
    assert api.get("/api/finance/ohip-anomalies", headers=lakeshore).json() == []
    earlier = api.get(
        "/api/finance/ohip-anomalies?to=2026-08-31", headers=auth(clinichub, GROUP)
    ).json()
    assert earlier == []


def test_before_the_first_run_the_answers_are_empty(
    tmp_path: Path, clinichub: FakeClinicHub
) -> None:
    api = client_for(tmp_path, clinichub, scored=False)
    body = api.get("/api/models/revenue-forecast", headers=auth(clinichub, GROUP, MODELS)).json()
    assert body == {"run": None, "series": []}
    assert api.get("/api/finance/ohip-anomalies", headers=auth(clinichub, GROUP)).json() == []
