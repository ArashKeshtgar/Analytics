FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1
# Microsoft ODBC Driver 18 for SQL Server (used from phase 1).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg ca-certificates unixodbc \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src src
COPY dbt dbt
RUN uv sync --frozen --no-dev
# The environment's own commands: `uv run` would sync (and compile) again at every start.
ENV ANALYTICS_HOST=0.0.0.0 PATH=/app/.venv/bin:$PATH
EXPOSE 5600
# The same image runs the scheduler (`analytics schedule`) and the consumer (`analytics consume`).
CMD ["analytics", "serve"]
