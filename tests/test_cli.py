import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from typer.testing import CliRunner

from analytics.cli import app

runner = CliRunner()


def test_extract_finance_is_honest_about_not_being_built() -> None:
    result = runner.invoke(app, ["extract", "finance"])
    assert result.exit_code == 2


def test_build_runs_dbt_on_the_empty_project(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANALYTICS_WAREHOUSE_PATH", str(tmp_path / "w.duckdb"))
    monkeypatch.setenv("ANALYTICS_DATA_DIR", str(tmp_path))
    result = runner.invoke(app, ["build"])
    assert result.exit_code == 0, result.output


def test_serve_answers_on_a_port() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [sys.executable, "-m", "analytics.cli_main", "serve", "--port", str(port)]
    )
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as r:
                    assert r.status == 200
                    return
            except OSError:
                time.sleep(0.2)
        raise AssertionError("server did not answer")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
