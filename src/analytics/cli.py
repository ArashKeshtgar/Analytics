import threading
from typing import Annotated

import typer
import uvicorn

from analytics.events import ConsumerError, run_forever
from analytics.events import consume as consume_events
from analytics.extract import extract_finance
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


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Defaults to ANALYTICS_HOST.")] = None,
    port: Annotated[int | None, typer.Option(help="Defaults to ANALYTICS_PORT (5600).")] = None,
) -> None:
    """Start the API."""
    settings = get_settings()
    uvicorn.run("analytics.api:app", host=host or settings.host, port=port or settings.port)
