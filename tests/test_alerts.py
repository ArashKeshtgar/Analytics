"""The failed-run alert: told once, again after a day, and when the run works again."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from analytics import alerts
from analytics.pipeline import Check, Report, Step, load_reports, run
from analytics.settings import Settings
from tests.conftest import make_settings
from tests.test_run import DAY, failing, synthetic

URL = "http://alerts.invalid/hook?secret=abc"


class Hook:
    """Stands in for the webhook: keeps what was posted, can be made to refuse."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, takes: bool = True) -> None:
        self.sent: list[dict[str, Any]] = []
        self.takes = takes
        monkeypatch.setattr(alerts, "post", self.post)

    def post(self, url: str, body: dict[str, Any]) -> bool:
        assert url == URL
        if self.takes:
            self.sent.append(body)
        return self.takes


def settings_with_hook(tmp_path: Path, **extra: Any) -> Settings:
    return make_settings(tmp_path, alert_webhook_url=URL, **extra)


def report(status: str, hours: float, alert: str = "") -> Report:
    at = (DAY + timedelta(hours=hours)).isoformat()
    return Report(run_id=f"r{hours}", started_utc=at, finished_utc=at, status=status, alert=alert)


def test_the_first_failed_run_is_told_with_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = Hook(monkeypatch)
    settings = settings_with_hook(tmp_path)
    result = run(settings, now=DAY, extractor=failing)
    assert result.status == "failed" and result.alert == "failed"
    [body] = hook.sent
    assert body["state"] == "failed" and body["runId"] == result.run_id
    assert body["failedSteps"] == [
        {"name": "extract", "detail": "ConnectionError: the finance server did not answer"}
    ]
    assert "extract: ConnectionError" in body["text"] and "last good data" in body["text"]
    assert load_reports(settings)[0]["alert"] == "failed"


def test_a_run_that_keeps_failing_is_not_told_again_within_the_repeat_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = Hook(monkeypatch)
    settings = settings_with_hook(tmp_path)
    run(settings, now=DAY, extractor=failing)
    second = run(settings, now=DAY + timedelta(hours=6), extractor=failing)
    assert second.alert == "" and len(hook.sent) == 1


def test_it_is_told_again_after_the_repeat_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = Hook(monkeypatch)
    settings = settings_with_hook(tmp_path, alert_repeat_hours=12)
    first = asdict(report("failed", 0, alert="failed"))
    soon, later = report("failed", 6), report("failed", 13)
    assert alerts.due(soon, [first], settings) is None
    assert alerts.due(later, [first], settings) == "failed"
    assert hook.sent == []


def test_a_webhook_that_is_down_is_tried_again_by_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = Hook(monkeypatch, takes=False)
    settings = settings_with_hook(tmp_path)
    first = run(settings, now=DAY, extractor=failing)
    assert first.status == "failed" and first.alert == ""  # not recorded: nobody was told
    hook.takes = True
    second = run(settings, now=DAY + timedelta(hours=6), extractor=failing)
    assert second.alert == "failed" and len(hook.sent) == 1


def test_the_first_good_run_after_a_told_failure_says_so_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = Hook(monkeypatch)
    settings = settings_with_hook(tmp_path)
    run(settings, now=DAY, extractor=failing)
    good = run(
        settings, now=DAY + timedelta(hours=6), extractor=synthetic(DAY + timedelta(hours=6))
    )
    assert good.status == "ok" and good.alert == "recovered"
    assert [b["state"] for b in hook.sent] == ["failed", "recovered"]
    again = run(
        settings, now=DAY + timedelta(hours=12), extractor=synthetic(DAY + timedelta(hours=12))
    )
    assert again.alert == "" and len(hook.sent) == 2


def test_a_failure_nobody_was_told_about_is_not_followed_by_a_recovery(tmp_path: Path) -> None:
    settings = settings_with_hook(tmp_path)
    assert alerts.due(report("ok", 6), [asdict(report("failed", 0))], settings) is None


def test_a_good_run_never_alerts_and_no_webhook_means_no_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook = Hook(monkeypatch)
    ok = run(settings_with_hook(tmp_path / "a"), now=DAY, extractor=synthetic(DAY))
    assert ok.status == "ok" and ok.alert == "" and hook.sent == []
    silent = make_settings(tmp_path / "b")  # no webhook set
    failed = run(silent, now=DAY, extractor=failing)
    assert failed.status == "failed" and failed.alert == "" and hook.sent == []


def test_post_reports_a_refusal_without_raising_and_never_logs_the_url(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert alerts.post("http://127.0.0.1:9/hook?secret=abc", {"text": "x"}) is False
    captured = capsys.readouterr()
    assert "secret" not in captured.out + captured.err


def test_the_body_names_the_error_checks_and_stays_small() -> None:
    r = report("failed", 0)
    r.steps = [Step("build", "failed", 1.0, "RuntimeError: dbt build failed")]
    r.checks = [Check("error", "step", "build", "RuntimeError: dbt build failed")] * 8
    body = alerts._body("failed", r)  # noqa: SLF001
    assert len(body["errors"]) == 5 and body["failedSteps"][0]["name"] == "build"
    assert datetime.fromisoformat(body["finishedUtc"]).tzinfo is UTC
