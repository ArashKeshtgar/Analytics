"""Old extracts and reports: past the window one extract a day stays, the history loses nothing."""

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from analytics import cli
from analytics.finance_tables import FINANCE_TABLES
from analytics.retention import prune
from analytics.settings import Settings
from analytics.warehouse import complete_runs
from tests.conftest import make_settings

NOW = datetime(2026, 11, 30, 9, tzinfo=UTC)


def extract(settings: Settings, run_id: str, complete: bool = True) -> None:
    folder = settings.data_dir / "raw" / "finance" / run_id
    folder.mkdir(parents=True)
    tables = FINANCE_TABLES if complete else FINANCE_TABLES[:1]
    for table in tables:
        (folder / f"{table.raw_name}.parquet").write_bytes(b"x")


def names(settings: Settings) -> list[str]:
    return sorted(p.name for p in (settings.data_dir / "raw" / "finance").iterdir())


def report(settings: Settings, run_id: str, replaced: bool = False) -> None:
    folder = settings.data_dir / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "warehouse_replaced": replaced}), encoding="utf-8"
    )


def test_past_the_window_only_the_last_extract_of_each_day_stays(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, keep_extract_days=14)
    for run_id in (
        "20261101T060000Z",  # old: the first of its day goes
        "20261101T180000Z",  # old: the last of its day stays (the history snapshot)
        "20261102T060000Z",  # old, alone in its day: stays
        "20261120T060000Z",  # inside the window: both stay
        "20261120T180000Z",
    ):
        extract(settings, run_id)
    result = prune(settings, now=NOW)
    assert result.extracts == ["20261101T060000Z"]
    assert names(settings) == [
        "20261101T180000Z",
        "20261102T060000Z",
        "20261120T060000Z",
        "20261120T180000Z",
    ]
    assert len(complete_runs(settings)) == 4


def test_a_partial_extract_past_the_window_goes_and_a_recent_one_stays(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, keep_extract_days=14)
    extract(settings, "20261101T060000Z", complete=False)
    extract(settings, "20261129T060000Z", complete=False)
    prune(settings, now=NOW)
    assert names(settings) == ["20261129T060000Z"]


def test_a_dry_run_deletes_nothing_and_zero_keeps_everything(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, keep_extract_days=14)
    extract(settings, "20261101T060000Z")
    extract(settings, "20261101T180000Z")
    assert prune(settings, now=NOW, dry_run=True).extracts == ["20261101T060000Z"]
    assert len(names(settings)) == 2
    keep_all = make_settings(tmp_path, keep_extract_days=0, keep_reports=0)
    assert prune(keep_all, now=NOW).describe() == "nothing to delete"
    assert len(names(settings)) == 2


def test_reports_beyond_the_limit_go_but_the_last_good_one_never(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, keep_reports=2)
    report(settings, "20261101T000000Z", replaced=True)  # the last good one, oldest
    for day in ("02", "03", "04", "05"):
        report(settings, f"202611{day}T000000Z")  # failed runs
    result = prune(settings, now=NOW)
    assert sorted(result.reports) == ["20261102T000000Z.json", "20261103T000000Z.json"]
    left = sorted(p.name for p in (settings.data_dir / "runs").iterdir())
    assert left == ["20261101T000000Z.json", "20261104T000000Z.json", "20261105T000000Z.json"]


def test_nothing_on_disk_is_nothing_to_delete(tmp_path: Path) -> None:
    assert prune(make_settings(tmp_path), now=NOW).describe() == "nothing to delete"


def test_the_command_says_what_it_deletes(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = make_settings(tmp_path, keep_extract_days=14)
    extract(settings, "20200101T060000Z")
    extract(settings, "20200101T180000Z")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    runner = CliRunner()
    dry = runner.invoke(cli.app, ["prune", "--dry-run"])
    assert dry.exit_code == 0 and "would delete: 1 extracts, 0 reports" in dry.output
    assert "20200101T060000Z" in dry.output and len(names(settings)) == 2
    done = runner.invoke(cli.app, ["prune"])
    assert "deleted: 1 extracts" in done.output and names(settings) == ["20200101T180000Z"]
