"""Old data (phase 6): finance extracts and run reports are not kept forever.

An extract older than `keep_extract_days` is deleted unless it is the last complete one of its
day, because that one is what the open-item history is built from (`load_raw`): the history loses
nothing, and `data/` grows by one extract a day instead of one a run. Partial extracts (a run that
died halfway) older than that go too. Reports are kept newest first up to `keep_reports`, and the
last one that replaced the warehouse is always kept (the row-count comparison reads it).
"""

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from analytics.settings import Settings
from analytics.warehouse import RAW_FINANCE, complete_runs, run_date


@dataclass
class Pruned:
    extracts: list[str] = field(default_factory=list)
    reports: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if not self.extracts and not self.reports:
            return "nothing to delete"
        return f"{len(self.extracts)} extracts, {len(self.reports)} reports"


def runs_dir(settings: Settings) -> Path:
    """The run reports' folder (as `pipeline.runs_dir`, which imports this module)."""
    return settings.data_dir / "runs"


def _run_day(name: str) -> date | None:
    try:
        return run_date(name)
    except ValueError:
        return None


def old_extracts(settings: Settings, today: date) -> list[str]:
    if settings.keep_extract_days <= 0:
        return []
    base = settings.data_dir / "raw" / RAW_FINANCE
    if not base.is_dir():
        return []
    cutoff = today - timedelta(days=settings.keep_extract_days)
    last_of_day: dict[date, str] = {}
    for name in complete_runs(settings):
        day = _run_day(name)
        if day is not None:
            last_of_day[day] = name
    keep = set(last_of_day.values())
    doomed = []
    for folder in sorted(base.iterdir()):
        day = _run_day(folder.name)
        if not folder.is_dir() or day is None or day >= cutoff or folder.name in keep:
            continue
        doomed.append(folder.name)
    return doomed


def _replaced(path: Path) -> bool:
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("warehouse_replaced"))
    except (OSError, json.JSONDecodeError):
        return False


def old_reports(settings: Settings) -> list[str]:
    if settings.keep_reports <= 0:
        return []
    folder = runs_dir(settings)
    if not folder.is_dir():
        return []
    files = sorted(folder.glob("*.json"), reverse=True)
    last_good = next((p for p in files if _replaced(p)), None)
    return [p.name for p in files[settings.keep_reports :] if p != last_good]


def prune(settings: Settings, now: datetime | None = None, dry_run: bool = False) -> Pruned:
    today = (now or datetime.now(UTC)).astimezone(UTC).date()
    result = Pruned(old_extracts(settings, today), old_reports(settings))
    if dry_run:
        return result
    base = settings.data_dir / "raw" / RAW_FINANCE
    for name in result.extracts:
        shutil.rmtree(base / name)
    for name in result.reports:
        (runs_dir(settings) / name).unlink(missing_ok=True)
    return result
