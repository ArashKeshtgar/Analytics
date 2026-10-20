"""Telling somebody that a run failed, and that it works again (phase 6).

The webhook gets a JSON POST: `text` (a sentence, readable as it is in chat tools) and the details.
The report on disk records that the webhook took the message (`alert`), which is all the state
there is: the first failed run is told, the failed runs after it are not (until
`alert_repeat_hours` have passed), and the first good run after a told failure says so. A webhook
that is down is tried again by the next run. Nothing here raises: an alert must not break a run.
"""

import json
import urllib.request
from datetime import datetime
from typing import Any

from analytics.settings import Settings

ALERT_FAILED = "failed"
ALERT_RECOVERED = "recovered"
TIMEOUT_SECONDS = 10


def post(url: str, body: dict[str, Any]) -> bool:
    """True when the webhook answered 2xx. The URL can hold a secret, so it is never logged."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
            return bool(200 <= response.status < 300)
    except Exception:
        return False


def _streak(previous: list[dict[str, Any]]) -> tuple[bool, dict[str, Any] | None]:
    """(the last run failed, the newest report of that failed streak that was told), from newest."""
    if not previous or previous[0].get("status") != "failed":
        return False, None
    for report in previous:
        if report.get("status") != "failed":
            break
        if report.get("alert") == ALERT_FAILED:
            return True, report
    return True, None


def _parse(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def due(report: Any, previous: list[dict[str, Any]], settings: Settings) -> str | None:
    """Which message this run owes: `failed`, `recovered` or nothing."""
    was_failing, told = _streak(previous)
    if report.status == "failed":
        if told is None:
            return ALERT_FAILED
        then, now = _parse(told.get("finished_utc", "")), _parse(report.finished_utc)
        if then and now and (now - then).total_seconds() >= settings.alert_repeat_hours * 3600:
            return ALERT_FAILED
        return None
    return ALERT_RECOVERED if was_failing and told is not None else None


def _body(state: str, report: Any) -> dict[str, Any]:
    failed = [s for s in report.steps if s.status == "failed"]
    errors = [c for c in report.checks if c.level == "error"][:5]
    if state == ALERT_FAILED:
        reason = "; ".join(f"{s.name}: {s.detail}" for s in failed) or "see the run report"
        text = (
            f"Analytics run {report.run_id} failed ({reason}). "
            "The dashboard still shows the last good data."
        )
    else:
        text = f"Analytics run {report.run_id} worked again ({report.status})."
    return {
        "service": "analytics",
        "state": state,
        "runId": report.run_id,
        "status": report.status,
        "startedUtc": report.started_utc,
        "finishedUtc": report.finished_utc,
        "failedSteps": [{"name": s.name, "detail": s.detail} for s in failed],
        "errors": [{"subject": c.subject, "message": c.message} for c in errors],
        "text": text,
    }


def notify(report: Any, previous: list[dict[str, Any]], settings: Settings) -> str:
    """Sends what this run owes. Returns what was told ('failed', 'recovered') or '' for nothing."""
    if not settings.alert_webhook_url:
        return ""
    state = due(report, previous, settings)
    if state is None:
        return ""
    return state if post(settings.alert_webhook_url, _body(state, report)) else ""
