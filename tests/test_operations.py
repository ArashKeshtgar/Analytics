"""Events -> warehouse -> dbt -> API, against the numbers worked out in synthetic_events.py."""

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
from tests import synthetic_events, synthetic_source
from tests.conftest import DASHBOARD, GROUP, FakeClinicHub, make_settings
from tests.synthetic_events import store_events

OPS = "/api/operations"


@pytest.fixture(scope="module")
def group(auth_settings_ops: Settings, clinichub: FakeClinicHub) -> TestClient:
    token = clinichub.token(permission=[GROUP])
    return TestClient(create_app(auth_settings_ops), headers={"Authorization": f"Bearer {token}"})


def clinic(settings: Settings, hub: FakeClinicHub, slug: str) -> TestClient:
    token = hub.token(permission=[DASHBOARD], clinic_slug=slug)
    return TestClient(create_app(settings), headers={"Authorization": f"Bearer {token}"})


def get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(OPS + path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def warehouse(built_ops: Settings) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(built_ops.warehouse_path), read_only=True)


# ---- fact_order ---------------------------------------------------------------------------------


def orders(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    cursor = con.execute("select * from main.fact_order")
    names = [c[0] for c in cursor.description]
    return {row[1].split("|")[1]: dict(zip(names, row, strict=True)) for row in cursor.fetchall()}


def test_every_order_has_one_row_with_its_status_and_department(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    got = orders(warehouse)
    assert {k: v["status"] for k, v in got.items()} == {
        "101": "resulted",
        "102": "resulted",
        "103": "resulted",
        "104": "cancelled",
        "105": "resulted",
        "106": "resulted",
        "107": "accepted",
        "108": "placed",
        "999": "resulted (placed before the hub)",
        "201": "resulted",
    }
    assert got["106"]["department"] == "Diagnostics" and got["101"]["department"] == "Lab"
    assert got["201"]["clinic_slug"] == "lakeshore"


def test_turnaround_is_minutes_from_placed_to_the_first_final_result(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    got = orders(warehouse)
    assert {
        k: got[k]["turnaround_minutes"] for k in ("101", "102", "103", "105", "106", "201")
    } == {
        "101": 270.0,
        "102": 60.0,
        "103": 600.0,
        "105": 45.0,
        "106": 2880.0,
        "201": 60.0,
    }
    assert got["104"]["turnaround_minutes"] is None and got["107"]["turnaround_minutes"] is None


def test_events_that_arrive_out_of_order_still_make_one_complete_order(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    o = orders(warehouse)["102"]  # its result event was delivered before its order events
    assert o["placed_at"] == datetime(2026, 10, 5, 9, 0)
    assert o["accepted_at"] == datetime(2026, 10, 5, 9, 0, 5)
    assert o["first_final_at"] == datetime(2026, 10, 5, 10, 0)
    assert (o["test_code"], o["priority"]) == ("2160-0", "urgent")


def test_amendments_and_refused_cancels_are_counted_on_the_order(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    got = orders(warehouse)
    assert (got["103"]["amended_count"], got["103"]["last_amended_at"]) == (
        1,
        datetime(2026, 10, 7, 8),
    )
    assert got["105"]["cancel_refused_count"] == 1 and got["105"]["status"] == "resulted"
    assert got["104"]["cancelled_at"] == datetime(2026, 10, 7, 9)


def test_a_result_for_an_order_the_hub_never_saw_has_no_turnaround(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    o = orders(warehouse)["999"]
    assert o["placed_at"] is None and o["turnaround_minutes"] is None
    assert o["test_code"] == "6690-2" and o["patient_pseudonym"] is None


def test_the_same_patient_has_the_same_pseudonym_and_only_pseudonyms_are_kept(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    got = orders(warehouse)
    assert got["101"]["patient_pseudonym"] == got["103"]["patient_pseudonym"]
    assert got["101"]["patient_pseudonym"] != got["102"]["patient_pseudonym"]
    columns = {
        r[0]
        for r in warehouse.execute(
            "select column_name from information_schema.columns where table_name in "
            "('clinical_event', 'stg_clinical_event', 'fact_order')"
        ).fetchall()
    }
    assert not columns & {
        "name",
        "patient_name",
        "mrn",
        "health_card",
        "birth_date",
        "note",
        "value",
    }


def test_the_warehouse_keeps_one_row_per_event(warehouse: duckdb.DuckDBPyConnection) -> None:
    events = synthetic_events.all_events()
    assert warehouse.execute("select count(*) from raw.clinical_event").fetchone() == (len(events),)


# ---- marts --------------------------------------------------------------------------------------


def test_mart_turnaround_by_clinic_month_department_test_and_priority(
    warehouse: duckdb.DuckDBPyConnection,
) -> None:
    rows = warehouse.execute(
        "select orders_placed, orders_resulted, median_minutes, p90_minutes "
        "from main.mart_turnaround "
        "where clinic_slug = 'harbourview' and department = 'Lab' and test_code = '718-7' "
        "and priority = 'routine'"
    ).fetchall()
    # orders 101 (270 min), 103 (600), 104 (cancelled), 107 (waiting)
    assert rows == [(4, 2, 435.0, 567.0)]


def test_mart_cancellations(warehouse: duckdb.DuckDBPyConnection) -> None:
    rows = warehouse.execute(
        "select clinic_slug, month, department, test_code, cancelled, cancel_refused "
        "from main.mart_cancellations order by test_code"
    ).fetchall()
    assert rows == [
        ("harbourview", datetime(2026, 10, 1).date(), "Lab", "2160-0", 0, 1),
        ("harbourview", datetime(2026, 10, 1).date(), "Lab", "718-7", 1, 0),
    ]


# ---- the API ------------------------------------------------------------------------------------


def test_turnaround_for_everything(group: TestClient) -> None:
    assert get(group, "/turnaround", groupBy="none") == [
        {
            "placed": 9,
            "resulted": 6,
            "cancelled": 1,
            "pending": 2,
            "median_minutes": 165.0,
            "p90_minutes": 1740.0,
        }
    ]


def test_turnaround_by_month_is_the_month_the_order_was_placed(group: TestClient) -> None:
    rows = get(group, "/turnaround")
    assert [(r["month"], r["placed"]) for r in rows] == [("2026-10-01", 9)]


def test_turnaround_by_department_for_a_clinic(group: TestClient) -> None:
    rows = get(group, "/turnaround", groupBy="department", clinic="harbourview")
    assert rows == [
        {
            "department": "Diagnostics",
            "placed": 1,
            "resulted": 1,
            "cancelled": 0,
            "pending": 0,
            "median_minutes": 2880.0,
            "p90_minutes": 2880.0,
        },
        {
            "department": "Lab",
            "placed": 7,
            "resulted": 4,
            "cancelled": 1,
            "pending": 2,
            "median_minutes": 165.0,
            "p90_minutes": 501.0,
        },
    ]


def test_turnaround_by_test_in_one_department(group: TestClient) -> None:
    rows = get(group, "/turnaround", groupBy="test", clinic="harbourview", department="Lab")
    by_test = {r["test"]: r for r in rows}
    assert (by_test["718-7"]["placed"], by_test["718-7"]["resulted"]) == (5, 2)
    assert (by_test["718-7"]["median_minutes"], by_test["718-7"]["p90_minutes"]) == (435.0, 567.0)
    assert (by_test["2160-0"]["placed"], by_test["2160-0"]["resulted"]) == (2, 2)
    assert (by_test["2160-0"]["median_minutes"], by_test["2160-0"]["p90_minutes"]) == (52.5, 58.5)


def test_turnaround_by_priority(group: TestClient) -> None:
    rows = {
        r["priority"]: r
        for r in get(group, "/turnaround", groupBy="priority", clinic="harbourview")
    }
    assert (rows["routine"]["placed"], rows["routine"]["resulted"]) == (6, 4)
    assert (rows["routine"]["median_minutes"], rows["routine"]["p90_minutes"]) == (435.0, 2196.0)
    assert (rows["urgent"]["placed"], rows["urgent"]["median_minutes"]) == (1, 60.0)
    assert (rows["stat"]["placed"], rows["stat"]["resulted"], rows["stat"]["median_minutes"]) == (
        1,
        0,
        None,
    )


def test_turnaround_by_more_than_one_thing(group: TestClient) -> None:
    rows = get(group, "/turnaround", groupBy="clinic,department")
    assert [(r["clinic"], r["department"], r["placed"]) for r in rows] == [
        ("harbourview", "Diagnostics", 1),
        ("harbourview", "Lab", 7),
        ("lakeshore", "Lab", 1),
    ]


def test_a_range_without_orders_is_empty(group: TestClient) -> None:
    assert get(group, "/turnaround", **{"from": "2026-11-01"}) == []
    totals = get(group, "/turnaround", groupBy="none", **{"to": "2026-09-01"})
    assert totals[0]["placed"] == 0 and totals[0]["median_minutes"] is None


def test_cancellations_with_what_was_placed(group: TestClient) -> None:
    assert get(group, "/cancellations", clinic="harbourview") == [
        {
            "month": "2026-10-01",
            "department": "Diagnostics",
            "placed": 1,
            "cancelled": 0,
            "cancel_refused": 0,
        },
        {
            "month": "2026-10-01",
            "department": "Lab",
            "placed": 7,
            "cancelled": 1,
            "cancel_refused": 1,
        },
    ]
    lab = get(group, "/cancellations", department="Lab")
    assert [(r["placed"], r["cancelled"], r["cancel_refused"]) for r in lab] == [(8, 1, 1)]


def test_range_of_the_events(group: TestClient) -> None:
    assert get(group, "/range") == {"firstMonth": "2026-10-01", "lastMonth": "2026-10-01"}


# ---- who sees what ------------------------------------------------------------------------------


def test_a_clinic_sees_only_its_own_orders(
    auth_settings_ops: Settings, clinichub: FakeClinicHub
) -> None:
    mine = get(clinic(auth_settings_ops, clinichub, "harbourview"), "/turnaround", groupBy="clinic")
    assert [(r["clinic"], r["placed"]) for r in mine] == [("harbourview", 8)]
    other = get(clinic(auth_settings_ops, clinichub, "lakeshore"), "/turnaround", groupBy="none")
    assert other[0]["placed"] == 1 and other[0]["median_minutes"] == 60.0


def test_asking_for_another_clinic_gives_nothing_not_its_numbers(
    auth_settings_ops: Settings, clinichub: FakeClinicHub
) -> None:
    client = clinic(auth_settings_ops, clinichub, "harbourview")
    assert get(client, "/turnaround", clinic="lakeshore") == []
    assert get(client, "/cancellations", clinic="lakeshore") == []
    assert get(client, "/range", clinic="lakeshore") == {"firstMonth": None, "lastMonth": None}


def test_a_clinic_nobody_knows_sees_nothing(
    auth_settings_ops: Settings, clinichub: FakeClinicHub
) -> None:
    client = clinic(auth_settings_ops, clinichub, "elsewhere")
    assert get(client, "/turnaround") == [] and get(client, "/cancellations") == []


@pytest.mark.parametrize("path", ["/turnaround", "/cancellations", "/range"])
def test_the_operations_endpoints_need_a_finance_or_dashboard_permission(
    auth_settings_ops: Settings, clinichub: FakeClinicHub, path: str
) -> None:
    client = TestClient(create_app(auth_settings_ops))
    assert client.get(OPS + path).status_code == 401
    token = clinichub.token(permission=["analytics:models.view"])
    assert client.get(OPS + path, headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_bad_parameters_are_422(group: TestClient) -> None:
    assert group.get(OPS + "/turnaround", params={"groupBy": "patient"}).status_code == 422
    assert group.get(OPS + "/turnaround", params={"department": "Pharmacy"}).status_code == 422
    assert group.get(OPS + "/cancellations", params={"department": "x"}).status_code == 422
    # text from the request is never part of the SQL
    assert get(group, "/turnaround", clinic="x' or '1'='1") == []


# ---- the build ----------------------------------------------------------------------------------


def test_a_result_before_its_order_fails_the_build(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    extract_finance(
        DuckDbSource(synthetic_source.create()),
        settings,
        now=datetime(2026, 10, 31, 12, tzinfo=UTC),
    )
    placed = synthetic_events.event(
        "order.placed", "harbourview", "1", synthetic_events.day(5, "10:00")
    )
    early = synthetic_events.event(
        "result.final", "harbourview", "1", synthetic_events.day(5, "09:00"), status="final"
    )
    store_events(settings, [placed, early])
    assert build(settings) != 0


def test_it_builds_with_no_events_at_all(auth_settings: Settings, built: Settings) -> None:
    # the finance-only warehouse of the other tests: the models exist and are empty
    con = duckdb.connect(str(built.warehouse_path), read_only=True)
    assert con.execute("select count(*) from main.fact_order").fetchone() == (0,)
    assert con.execute("select count(*) from main.mart_turnaround").fetchone() == (0,)
