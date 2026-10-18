from fastapi import FastAPI

from analytics import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="Analytics", version=__version__)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/version")
    def version() -> dict[str, str]:
        return {"name": "analytics", "version": __version__}

    return app


app = create_app()
