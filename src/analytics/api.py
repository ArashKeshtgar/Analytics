from datetime import date
from typing import Annotated, Any

import duckdb
from fastapi import FastAPI, HTTPException, Query

from analytics import __version__
from analytics.settings import Settings, get_settings

# groupBy value -> (select expression, output name, order). Fixed list: nothing from the request
# is ever placed in SQL text.
_REVENUE_GROUPS = {
    "month": "r.month",
    "business": "b.code as business",
    "lineOfBusiness": "r.line_of_business",
    "provider": "r.provider_code as provider",
}

_BUSINESS_FILTER = (
    "r.business_id in (select business_id from main.dim_business "
    "where lower(code) = lower(?) or lower(clinic_slug) = lower(?))"
)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Analytics", version=__version__)

    def query(sql: str, params: list[Any]) -> list[dict[str, Any]]:
        # Sign-in and clinic scoping arrive in phase 2: until then these endpoints are open and
        # the service listens on localhost only.
        path = (settings or get_settings()).warehouse_path
        if not path.is_file():
            raise HTTPException(503, "The warehouse is not built yet. Run `analytics build`.")
        con = duckdb.connect(str(path), read_only=True)
        try:
            cursor = con.execute(sql, params)
            names = [c[0] for c in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        except duckdb.CatalogException as exc:
            raise HTTPException(503, "The warehouse has no finance data yet.") from exc
        finally:
            con.close()

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/version")
    def version() -> dict[str, str]:
        return {"name": "analytics", "version": __version__}

    @app.get("/api/finance/revenue")
    def revenue(
        business: str | None = None,
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
        group_by: Annotated[str, Query(alias="groupBy")] = "month",
    ) -> list[dict[str, Any]]:
        keys = [k.strip() for k in group_by.split(",") if k.strip()]
        unknown = [k for k in keys if k not in _REVENUE_GROUPS]
        if not keys or unknown:
            raise HTTPException(422, f"groupBy must be a list of: {', '.join(_REVENUE_GROUPS)}")
        columns = ", ".join(_REVENUE_GROUPS[k] for k in keys)
        where, params = _filters(business, from_, to)
        sql = (
            f"select {columns}, round(sum(r.revenue), 2)::double as revenue "
            "from main.mart_revenue_monthly r join main.dim_business b using (business_id) "
            f"{where} group by {', '.join(str(i + 1) for i in range(len(keys)))} "
            f"order by {', '.join(str(i + 1) for i in range(len(keys)))}"
        )
        return query(sql, params)

    @app.get("/api/finance/ohip-collection")
    def ohip_collection(
        business: str | None = None,
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _filters(business, from_, to)
        sql = (
            "select b.code as business, r.month, "
            "r.billed::double as billed, r.paid::double as paid, r.adjusted::double as adjusted, "
            "r.outstanding::double as outstanding, r.short_paid::double as short_paid, "
            "r.refused::double as refused, r.short_paid_rate::double as short_paid_rate, "
            "r.refused_rate::double as refused_rate "
            "from main.mart_ohip_collection r join main.dim_business b using (business_id) "
            f"{where} order by b.code, r.month"
        )
        return query(sql, params)

    @app.get("/api/finance/aging")
    def aging(
        business: str | None = None,
        as_of: Annotated[date | None, Query(alias="asOf")] = None,
        side: str = "receivable",
    ) -> list[dict[str, Any]]:
        if side not in ("receivable", "payable"):
            raise HTTPException(422, "side must be receivable or payable")
        cte_params: list[Any] = [side]
        cte_extra = ""
        if as_of:
            cte_extra = " and snapshot_date <= ?"
            cte_params.append(as_of)
        main_params: list[Any] = [side]
        biz = ""
        if business:
            biz = " and " + _BUSINESS_FILTER.replace("r.business_id", "s.business_id")
            main_params += [business, business]
        sql = (
            "with latest as (select max(snapshot_date) as d from main.fact_open_item_snapshot "
            f"where side = ?{cte_extra}) "
            "select b.code as business, p.party_type, s.aging_bucket, s.snapshot_date, "
            "round(sum(s.balance), 2)::double as balance, count(*) as items "
            "from main.fact_open_item_snapshot s join latest on s.snapshot_date = latest.d "
            "join main.dim_business b on b.business_id = s.business_id "
            "join main.dim_party p on p.party_id = s.party_id "
            f"where s.side = ?{biz} "
            "group by 1, 2, 3, 4 order by 1, 2, 3"
        )
        return query(sql, cte_params + main_params)

    return app


def _filters(business: str | None, from_: date | None, to: date | None) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if business:
        clauses.append(_BUSINESS_FILTER)
        params += [business, business]
    if from_:
        clauses.append("r.month >= date_trunc('month', ?::date)")
        params.append(from_)
    if to:
        clauses.append("r.month <= ?::date")
        params.append(to)
    return (("where " + " and ".join(clauses)) if clauses else ""), params


app = create_app()
