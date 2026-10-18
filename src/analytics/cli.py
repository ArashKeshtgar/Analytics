import subprocess
from typing import Annotated

import typer
import uvicorn

from analytics.settings import get_settings

app = typer.Typer(help="Analytics: extract, build and serve the warehouse.", no_args_is_help=True)
extract_app = typer.Typer(help="Copy data from a source into data/raw/.", no_args_is_help=True)
app.add_typer(extract_app, name="extract")


@extract_app.command("finance")
def extract_finance() -> None:
    """Extract FinancePowerApp (phase 1, not built yet)."""
    typer.echo("extract finance is not built yet (phase 1).", err=True)
    raise typer.Exit(code=2)


@app.command()
def build() -> None:
    """Run the dbt project against the DuckDB warehouse."""
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "dbt",
            "build",
            "--project-dir",
            str(settings.dbt_project_dir),
            "--profiles-dir",
            str(settings.dbt_project_dir),
        ],
        check=False,
    )
    raise typer.Exit(code=result.returncode)


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Defaults to ANALYTICS_HOST.")] = None,
    port: Annotated[int | None, typer.Option(help="Defaults to ANALYTICS_PORT (5600).")] = None,
) -> None:
    """Start the API."""
    settings = get_settings()
    uvicorn.run("analytics.api:app", host=host or settings.host, port=port or settings.port)
