from typing import Annotated

import typer
import uvicorn

from analytics.extract import extract_finance
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
def build() -> None:
    """Load the raw extracts into data/warehouse.duckdb and run dbt (models and tests)."""
    raise typer.Exit(code=build_warehouse(get_settings()))


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Defaults to ANALYTICS_HOST.")] = None,
    port: Annotated[int | None, typer.Option(help="Defaults to ANALYTICS_PORT (5600).")] = None,
) -> None:
    """Start the API."""
    settings = get_settings()
    uvicorn.run("analytics.api:app", host=host or settings.host, port=port or settings.port)
