from collections.abc import Sequence
from typing import Any, Protocol

import duckdb
import polars as pl


class Source(Protocol):
    """A read-only database. Only `SELECT` text is ever passed to it."""

    def read(self, query: str) -> pl.DataFrame: ...

    def close(self) -> None: ...


def frame(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> pl.DataFrame:
    return pl.DataFrame(
        [tuple(r) for r in rows], schema=list(columns), orient="row", infer_schema_length=None
    )


class SqlServerSource:
    """FinancePowerApp through its read-only login (pyodbc, ODBC Driver 18)."""

    def __init__(self, connection_string: str) -> None:
        import pyodbc  # imported late: needs the ODBC driver library at import time

        self._con = pyodbc.connect(connection_string, readonly=True, timeout=30)

    def read(self, query: str) -> pl.DataFrame:
        cursor = self._con.cursor()
        cursor.execute(query)
        columns = [c[0] for c in cursor.description]
        return frame(columns, cursor.fetchall())

    def close(self) -> None:
        self._con.close()


class DuckDbSource:
    """A DuckDB database shaped like FinancePowerApp. Used by the tests."""

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self._con = con

    def read(self, query: str) -> pl.DataFrame:
        cursor = self._con.execute(query)
        columns = [c[0] for c in cursor.description]
        return frame(columns, cursor.fetchall())

    def close(self) -> None:
        pass
