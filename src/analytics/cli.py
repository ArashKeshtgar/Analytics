import re
import signal
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
import uvicorn

from analytics.events import ConsumerError, run_forever
from analytics.events import consume as consume_events
from analytics.extract import extract_finance
from analytics.pipeline import Report, describe_failure
from analytics.pipeline import run as run_pipeline
from analytics.retention import prune as prune_data
from analytics.scoring import ScoreError
from analytics.scoring import score as score_warehouse
from analytics.settings import get_settings
from analytics.sources import SqlServerSource
from analytics.warehouse import build as build_warehouse

app = typer.Typer(help="Analytics: extract, build and serve the warehouse.", no_args_is_help=True)
extract_app = typer.Typer(help="Copy data from a source into data/raw/.", no_args_is_help=True)
app.add_typer(extract_app, name="extract")


@extract_app.command("finance")
def extract_finance_command() -> None:
    """Extract FinancePowerApp (read-only login) to data/raw/finance/{run}/."""
    settings = get_settings()
    if not settings.finance_connection_string:
        typer.echo("Set ANALYTICS_FINANCE_CONNECTION_STRING (see .env.example).", err=True)
        raise typer.Exit(code=2)
    source = SqlServerSource(settings.finance_connection_string)
    try:
        result = extract_finance(source, settings)
    finally:
        source.close()
    typer.echo(f"Run {result.run_id}")
    for table, count in result.rows.items():
        typer.echo(f"  {table}: {count} rows")


@app.command()
def consume(
    drain: Annotated[bool, typer.Option(help="Read what is waiting, then stop.")] = False,
) -> None:
    """Read IntegrationHub's de-identified events from RabbitMQ into data/raw/events/."""
    settings = get_settings()
    stop = threading.Event()
    if drain:
        try:
            result = consume_events(settings, drain=True, stop=stop)
        except ConsumerError as e:
            typer.echo(str(e), err=True)
            raise typer.Exit(code=2) from None
        typer.echo(
            f"stored {result.stored}, rejected {result.rejected}, ignored {result.ignored}, "
            f"batches {result.batches}"
        )
        for reason, count in sorted(result.reasons.items()):
            typer.echo(f"  rejected: {reason} x{count}")
        return
    try:
        run_forever(settings, stop)
    except KeyboardInterrupt:
        stop.set()


@app.command()
def build() -> None:
    """Load the raw extracts into data/warehouse.duckdb and run dbt (models and tests)."""
    raise typer.Exit(code=build_warehouse(get_settings()))


@app.command()
def score() -> None:
    """Revenue forecasts (with backtests) and remittance anomalies into schema `ml`."""
    try:
        run = score_warehouse(get_settings())
    except ScoreError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from None
    typer.echo(f"Run {run.run_id}, complete months through {run.data_through:%Y-%m}")
    typer.echo(
        f"  revenue series: {run.series}, forecast {run.forecasts}, "
        f"too short {run.too_short} (need 18 months)"
    )
    typer.echo(f"  remittance: {run.scored} provider-months scored, {run.flagged} flagged")


def print_report(report: Report) -> None:
    typer.echo(f"Run {report.run_id}: {report.status}")
    for step in report.steps:
        detail = f" - {step.detail}" if step.detail else ""
        typer.echo(f"  {step.name:<8} {step.status:<8} {step.seconds:>7.1f} s{detail}")
    for check in report.checks:
        typer.echo(f"  {check.level}: {check.subject}: {check.message}")


@app.command()
def run() -> None:
    """Extract, build and score into a copy of the warehouse, swap it in, and write a report."""
    report = run_pipeline(get_settings())
    print_report(report)
    if report.status == "failed":
        raise typer.Exit(code=1)


@app.command()
def prune(
    dry_run: Annotated[bool, typer.Option(help="Say what would go, delete nothing.")] = False,
) -> None:
    """Delete old finance extracts (one per day is kept) and old run reports; see the settings."""
    result = prune_data(get_settings(), dry_run=dry_run)
    verb = "would delete" if dry_run else "deleted"
    typer.echo(f"{verb}: {result.describe()}")
    for name in result.extracts:
        typer.echo(f"  extract {name}")
    for name in result.reports:
        typer.echo(f"  report  {name}")


def parse_every(text: str) -> timedelta:
    """30m, 6h, 1d (or a combination such as 1h30m); at least a minute."""
    parts = re.fullmatch(r"\s*(?:(\d+)d)?\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*", text.lower())
    if not parts or not any(parts.groups()):
        raise typer.BadParameter(f"{text!r}: use a duration such as 30m, 6h or 1d")
    d, h, m = (int(g or 0) for g in parts.groups())
    every = timedelta(days=d, hours=h, minutes=m)
    if every < timedelta(minutes=1):
        raise typer.BadParameter("at least 1m")
    return every


@app.command()
def schedule(
    every: Annotated[str | None, typer.Option(help="Defaults to ANALYTICS_RUN_EVERY (6h).")] = None,
) -> None:
    """Run `analytics run` now and then every interval, until stopped (Ctrl+C or SIGTERM)."""
    settings = get_settings()
    interval = parse_every(every or settings.run_every)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    typer.echo(f"Running every {interval}; stop with Ctrl+C.")
    try:
        while not stop.is_set():
            started = time.monotonic()
            try:
                print_report(run_pipeline(settings))
            except Exception as exc:  # a broken run must not end the schedule
                typer.echo(f"run failed: {describe_failure(exc)}", err=True)
            wait = max(0.0, interval.total_seconds() - (time.monotonic() - started))
            nxt = datetime.now(UTC) + timedelta(seconds=wait)
            typer.echo(f"Next run at {nxt:%Y-%m-%d %H:%M} UTC.")
            stop.wait(wait)
    except KeyboardInterrupt:
        pass


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Defaults to ANALYTICS_HOST.")] = None,
    port: Annotated[int | None, typer.Option(help="Defaults to ANALYTICS_PORT (5600).")] = None,
) -> None:
    """Start the API."""
    settings = get_settings()
    uvicorn.run("analytics.api:app", host=host or settings.host, port=port or settings.port)
