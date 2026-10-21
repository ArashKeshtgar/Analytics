"""`analytics run` and `analytics schedule`: one pass of extract, build and score into a copy of the
warehouse, swapped in only when it worked, with a data-quality report per run."""

import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import typer
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from analytics import cli
from analytics.api import create_app
from analytics.extract import extract_finance
from analytics.pipeline import (
    Check,
    Report,
    checks_for,
    dbt_failures,
    load_reports,
    next_path,
    results_file,
    run,
)
from analytics.settings import Settings
from analytics.sources import DuckDbSource
from tests import synthetic_source
from tests.conftest import DASHBOARD, GROUP, ISSUER, FakeClinicHub, make_settings

DAY = datetime(2026, 11, 15, 12, tzinfo=UTC)


def synthetic(day: datetime = DAY):
    def extractor(settings: Settings) -> dict[str, int]:
        return extract_finance(DuckDbSource(synthetic_source.create()), settings, now=day).rows

    return extractor


def failing(settings: Settings) -> dict[str, int]:
    raise ConnectionError("the finance server did not answer\nsecond line with more detail")


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Settings, Report, Report]:
    settings = make_settings(tmp_path_factory.mktemp("run"))
    first = run(settings, now=DAY, extractor=synthetic(DAY))
    second = run(
        settings, now=DAY + timedelta(hours=6), extractor=synthetic(DAY + timedelta(hours=6))
    )
    return settings, first, second


def test_a_run_extracts_builds_scores_and_swaps_the_warehouse_in(
    two_runs: tuple[Settings, Report, Report],
) -> None:
    settings, first, _ = two_runs
    assert first.status == "ok", first.checks
    assert [(s.name, s.status) for s in first.steps] == [
        ("prepare", "ok"),
        ("extract", "ok"),
        ("labflow", "skipped"),  # test_labflow_dw.py gives it LabFlow's warehouse
        ("build", "ok"),
        ("reconcile", "skipped"),  # test_reconcile.py gives it the books
        ("score", "ok"),
        ("replace", "ok"),
        ("prune", "ok"),
    ]
    assert first.warehouse_replaced and settings.warehouse_path.is_file()
    assert not next_path(settings).exists()
    names = {t["name"] for t in first.tables}
    assert {"raw.gl_journalentry", "main.fact_gl_line", "main.mart_revenue_monthly"} <= names
    assert all(t["previous"] is None for t in first.tables)  # nothing to compare with yet


def test_the_next_run_compares_every_table_with_the_last_good_one(
    two_runs: tuple[Settings, Report, Report],
) -> None:
    _, first, second = two_runs
    assert second.status == "ok", second.checks
    before = {t["name"]: t["rows"] for t in first.tables}
    assert all(t["previous"] == before[t["name"]] for t in second.tables if t["name"] in before)


def test_reports_are_files_newest_first(two_runs: tuple[Settings, Report, Report]) -> None:
    settings, first, second = two_runs
    reports = load_reports(settings)
    assert [r["run_id"] for r in reports[:2]] == [second.run_id, first.run_id]
    on_disk = json.loads((settings.data_dir / "runs" / f"{first.run_id}.json").read_text())
    assert on_disk["steps"][0]["name"] == "prepare" and on_disk["warehouse_replaced"] is True


def test_a_failed_run_keeps_the_last_good_warehouse(
    two_runs: tuple[Settings, Report, Report],
) -> None:
    settings, _, _ = two_runs
    before = settings.warehouse_path.read_bytes()
    report = run(settings, now=DAY + timedelta(days=1), extractor=failing)
    assert report.status == "failed" and not report.warehouse_replaced
    assert [(s.name, s.status) for s in report.steps] == [
        ("prepare", "ok"),
        ("extract", "failed"),
        ("prune", "ok"),
    ]
    assert report.steps[1].detail == "ConnectionError: the finance server did not answer"
    assert [c.kind for c in report.checks] == ["step"]
    assert settings.warehouse_path.read_bytes() == before
    assert not next_path(settings).exists()
    assert load_reports(settings)[0]["status"] == "failed"


def test_without_a_connection_string_the_extract_is_skipped(
    two_runs: tuple[Settings, Report, Report],
) -> None:
    settings, _, _ = two_runs
    report = run(settings, now=DAY + timedelta(days=2))
    assert report.steps[1].status == "skipped" and "CONNECTION_STRING" in report.steps[1].detail
    assert report.status == "ok"  # the extracts already on disk are built again


def test_with_nothing_extracted_ever_the_run_fails_and_says_why(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    report = run(settings, now=DAY)
    assert report.status == "failed"
    assert [s.status for s in report.steps] == ["ok", "skipped", "skipped", "failed", "ok"]
    assert not settings.warehouse_path.exists() and not next_path(settings).exists()


def test_row_drops_empty_tables_and_failed_tests_become_warnings_and_errors() -> None:
    previous = {"raw.a": 100, "raw.b": 100, "raw.c": 5, "raw.d": 40, "raw.gone": 3}
    counts = {"raw.a": 79, "raw.b": 81, "raw.c": 1, "raw.d": 0}
    failures = [
        {
            "node": "test.analytics.unique_fact_order",
            "status": "fail",
            "failures": 2,
            "message": "2 rows",
        },
        {"node": "model.analytics.mart_x", "status": "error", "failures": None, "message": "boom"},
        {"node": "test.analytics.soft", "status": "warn", "failures": 1, "message": ""},
    ]
    checks = checks_for(counts, previous, failures)
    assert [(c.level, c.kind, c.subject) for c in checks] == [
        ("error", "dbt-test", "test.analytics.unique_fact_order"),
        ("error", "dbt-model", "model.analytics.mart_x"),
        ("warning", "dbt-test", "test.analytics.soft"),
        ("warning", "row-drop", "raw.a"),  # 21% fewer; raw.b (19%) and raw.c (small) are not news
        ("warning", "empty-table", "raw.d"),
    ]
    assert checks[3] == Check("warning", "row-drop", "raw.a", "100 rows last time, 79 now")


def test_failed_dbt_tests_are_read_from_dbts_results(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    path = results_file(settings)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "results": [
                    {"unique_id": "test.analytics.ok", "status": "pass"},
                    {
                        "unique_id": "test.analytics.bad",
                        "status": "fail",
                        "failures": 3,
                        "message": "x" * 400,
                    },
                ]
            }
        )
    )
    assert dbt_failures(settings) == [
        {"node": "test.analytics.bad", "status": "fail", "failures": 3, "message": "x" * 300}
    ]


# ---- the API -------------------------------------------------------------------------------------


def api_for(settings: Settings, clinichub: FakeClinicHub) -> TestClient:
    return TestClient(
        create_app(
            settings.model_copy(update={"oidc_issuer": ISSUER, "oidc_jwks_uri": clinichub.jwks_uri})
        )
    )


def bearer(clinichub: FakeClinicHub, *permission: str, clinic: str | None = None) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + clinichub.token(permission=list(permission), clinic_slug=clinic)
    }


def test_the_reports_are_served_to_the_group_only(
    two_runs: tuple[Settings, Report, Report], clinichub: FakeClinicHub
) -> None:
    settings, _, second = two_runs
    api = api_for(settings, clinichub)
    rows = api.get("/api/meta/runs?limit=2", headers=bearer(clinichub, GROUP)).json()
    assert len(rows) == 2 and {"steps", "tables", "checks", "status"} <= set(rows[0])
    assert second.run_id in {
        r["run_id"] for r in api.get("/api/meta/runs", headers=bearer(clinichub, GROUP)).json()
    }
    clinic = bearer(clinichub, DASHBOARD, clinic="harbourview")
    assert api.get("/api/meta/runs", headers=clinic).status_code == 403
    assert api.get("/api/meta/runs?limit=0", headers=bearer(clinichub, GROUP)).status_code == 422


def test_while_another_process_writes_the_warehouse_the_api_says_so(
    two_runs: tuple[Settings, Report, Report], clinichub: FakeClinicHub, tmp_path: Path
) -> None:
    settings, _, _ = two_runs
    copy = make_settings(tmp_path)
    copy.warehouse_path.parent.mkdir(parents=True)
    copy.warehouse_path.write_bytes(settings.warehouse_path.read_bytes())
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import duckdb, sys, time; c = duckdb.connect(sys.argv[1]); "
            "print('held', flush=True); time.sleep(60)",
            str(copy.warehouse_path),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        answer = api_for(copy, clinichub).get(
            "/api/finance/range", headers=bearer(clinichub, GROUP)
        )
        assert answer.status_code == 503
        assert "being updated" in answer.json()["detail"]
    finally:
        holder.kill()
        holder.wait()


# ---- the commands --------------------------------------------------------------------------------


def test_intervals() -> None:
    assert cli.parse_every("30m") == timedelta(minutes=30)
    assert cli.parse_every("6h") == timedelta(hours=6)
    assert cli.parse_every("1d") == timedelta(days=1)
    assert cli.parse_every("1h30m") == timedelta(minutes=90)
    for bad in ("", "soon", "0m", "10s"):
        with pytest.raises(typer.BadParameter):
            cli.parse_every(bad)


def test_the_run_command_exits_non_zero_when_the_run_failed(tmp_path: Path) -> None:
    env = {
        "ANALYTICS_DATA_DIR": str(tmp_path / "data"),
        "ANALYTICS_WAREHOUSE_PATH": str(tmp_path / "data" / "w.duckdb"),
    }
    result = CliRunner().invoke(cli.app, ["run"], env=env)
    assert result.exit_code == 1
    assert ": failed" in result.output and "extract   skipped" in result.output


class InstantEvent:
    """threading.Event whose wait does not wait: the schedule's pause, skipped in tests."""

    def __init__(self) -> None:
        self.flag = False
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return self.flag

    def set(self) -> None:
        self.flag = True

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        return self.flag


def test_the_schedule_survives_a_broken_run_and_stops_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    event = InstantEvent()

    def fake_run(settings: Any) -> Report:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("disk full")
        if len(calls) == 3:
            raise KeyboardInterrupt
        return Report(run_id="r2", started_utc="", status="ok")

    monkeypatch.setattr(cli, "run_pipeline", fake_run)
    monkeypatch.setattr(cli.threading, "Event", lambda: event)
    result = CliRunner().invoke(cli.app, ["schedule", "--every", "2h"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 3
    assert "run failed: RuntimeError: disk full" in result.output
    assert "Run r2: ok" in result.output
    assert all(0 < w <= 7200 for w in event.waits) and len(event.waits) == 2
    time.sleep(0)  # nothing left running
