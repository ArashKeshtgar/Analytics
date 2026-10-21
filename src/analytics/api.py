from datetime import date
from typing import Annotated, Any

import duckdb
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from analytics import __version__
from analytics.auth import (
    MODELS_VIEW,
    Forbidden,
    Scope,
    TokenVerifier,
    Unauthorized,
    Unavailable,
    User,
    scope_for,
)
from analytics.pipeline import load_reports
from analytics.settings import Settings, get_settings

# groupBy value -> select expression. Fixed list: nothing from the request goes into SQL text.
_REVENUE_GROUPS = {
    "month": "r.month",
    "business": "b.code as business",
    "lineOfBusiness": "r.line_of_business",
    "provider": "r.provider_code as provider",
}

# groupBy value -> select expression for the operations queries (fixed list, never request text).
_OPS_GROUPS = {
    "month": "date_trunc('month', o.placed_at)::date as month",
    "clinic": "o.clinic_slug as clinic",
    "department": "o.department as department",
    "test": "coalesce(o.test_code, 'unknown') as test",
    "priority": "coalesce(o.priority, 'unknown') as priority",
}
_DEPARTMENTS = ("Lab", "Diagnostics")

_BUSINESS_FILTER = (
    "{a}.business_id in (select business_id from main.dim_business "
    "where lower(code) = lower(?) or lower(clinic_slug) = lower(?))"
)
_SCOPE_FILTER = (
    "{a}.business_id in (select business_id from main.dim_business "
    "where lower(clinic_slug) = lower(?))"
)


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    verifier = TokenVerifier(config)
    app = FastAPI(title="Analytics", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.web_origin],
        allow_methods=["GET"],
        allow_headers=["Authorization"],
    )

    def current_user(request: Request) -> User:
        header = request.headers.get("Authorization", "")
        if header[:7].lower() != "bearer " or not header[7:].strip():
            raise HTTPException(401, "Sign in.", headers={"WWW-Authenticate": "Bearer"})
        try:
            return verifier.verify(header[7:].strip())
        except Unauthorized as exc:
            raise HTTPException(
                401, "The access token was not accepted.", headers={"WWW-Authenticate": "Bearer"}
            ) from exc
        except Unavailable as exc:
            raise HTTPException(503, "Tokens cannot be verified right now.") from exc

    def current_scope(user: Annotated[User, Depends(current_user)]) -> Scope:
        try:
            return scope_for(user)
        except Forbidden as exc:
            raise HTTPException(403, "No permission to view finance data.") from exc

    def models_scope(user: Annotated[User, Depends(current_user)]) -> Scope:
        """Model pages: `models.view`, and the same business scope as the rest."""
        if MODELS_VIEW not in user.permissions:
            raise HTTPException(403, "No permission to view models.")
        return current_scope(user)

    def latest_run() -> dict[str, Any] | None:
        """The latest `analytics score` run, or None before the first one."""
        found = query(
            "select count(*) as n from information_schema.tables "
            "where table_schema = 'ml' and table_name = 'run'",
            [],
        )
        if not found[0]["n"]:
            return None
        runs = query(
            'select run_id as "runId", created_utc as "createdUtc", '
            'data_through as "dataThrough" from ml.run '
            "order by created_utc desc, run_id desc limit 1",
            [],
        )
        return runs[0] if runs else None

    def query(sql: str, params: list[Any]) -> list[dict[str, Any]]:
        if not config.warehouse_path.is_file():
            raise HTTPException(503, "The warehouse is not built yet. Run `analytics build`.")
        try:
            con = duckdb.connect(str(config.warehouse_path), read_only=True)
        except duckdb.IOException as exc:
            # `analytics run` is swapping in a new warehouse (or a manual build is writing it).
            raise HTTPException(
                503, "The warehouse is being updated; try again in a moment."
            ) from exc
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

    @app.get("/api/me")
    def me(user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
        """Who the token says you are and what you may see; any valid token."""
        try:
            scope = "group" if scope_for(user).group else "clinic"
        except Forbidden:
            scope = "none"
        return {
            "name": user.name,
            "clinicSlug": user.clinic_slug,
            "permissions": sorted(user.permissions),
            "scope": scope,
        }

    @app.get("/api/finance/businesses")
    def businesses(scope: Annotated[Scope, Depends(current_scope)]) -> list[dict[str, Any]]:
        """The businesses the caller may see; the dashboard's business filter."""
        clauses, params = _business_clauses("d", scope, None)
        where = ("where " + " and ".join(clauses)) if clauses else ""
        sql = (
            'select d.code, d.name, d.kind, d.clinic_slug as "clinicSlug" '
            f"from main.dim_business d {where} order by d.code"
        )
        return query(sql, params)

    @app.get("/api/finance/range")
    def data_range(
        scope: Annotated[Scope, Depends(current_scope)], business: str | None = None
    ) -> dict[str, Any]:
        """First and last month with revenue in the caller's scope (null when none)."""
        clauses, params = _business_clauses("r", scope, business)
        where = ("where " + " and ".join(clauses)) if clauses else ""
        rows = query(
            'select min(r.month) as "firstMonth", max(r.month) as "lastMonth" '
            f"from main.mart_revenue_monthly r {where}",
            params,
        )
        return rows[0]

    def ops_clauses(
        alias: str,
        scope: Scope,
        clinic: str | None,
        department: str | None,
        from_: date | None,
        to: date | None,
        time_column: str,
    ) -> tuple[str, list[Any]]:
        """Filters of the operations queries. The clinic in the token always applies."""
        if department is not None and department not in _DEPARTMENTS:
            raise HTTPException(422, f"department must be one of: {', '.join(_DEPARTMENTS)}")
        clauses: list[str] = []
        params: list[Any] = []
        if not scope.group:
            clauses.append(f"lower({alias}.clinic_slug) = lower(?)")
            params.append(scope.clinic_slug)
        if clinic:
            clauses.append(f"lower({alias}.clinic_slug) = lower(?)")
            params.append(clinic)
        if department and alias == "o":
            clauses.append("o.department = ?")
            params.append(department)
        if from_:
            clauses.append(
                f"date_trunc('month', {alias}.{time_column}) >= date_trunc('month', ?::date)"
            )
            params.append(from_)
        if to:
            clauses.append(f"date_trunc('month', {alias}.{time_column}) <= ?::date")
            params.append(to)
        return (("where " + " and ".join(clauses)) if clauses else ""), params

    @app.get("/api/operations/range")
    def operations_range(
        scope: Annotated[Scope, Depends(current_scope)], clinic: str | None = None
    ) -> dict[str, Any]:
        """First and last month with events in the caller's scope (null when none)."""
        where, params = ops_clauses("e", scope, clinic, None, None, None, "occurred_at")
        rows = query(
            "select min(date_trunc('month', e.occurred_at))::date as \"firstMonth\", "
            "max(date_trunc('month', e.occurred_at))::date as \"lastMonth\" "
            f"from main.stg_clinical_event e {where}",
            params,
        )
        return rows[0]

    @app.get("/api/operations/turnaround")
    def turnaround(
        scope: Annotated[Scope, Depends(current_scope)],
        clinic: str | None = None,
        department: str | None = None,
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
        group_by: Annotated[str, Query(alias="groupBy")] = "month",
    ) -> list[dict[str, Any]]:
        """Orders, results and order-to-result time (median, 90th percentile, in minutes).

        Grouped by a comma list of month, clinic, department, test, priority; `groupBy=none` is one
        row for everything. Months are the month the order was placed.
        """
        keys = [k.strip() for k in group_by.split(",") if k.strip() and k.strip() != "none"]
        unknown = [k for k in keys if k not in _OPS_GROUPS]
        if unknown:
            raise HTTPException(422, f"groupBy must be a list of: {', '.join(_OPS_GROUPS)}")
        where, params = ops_clauses("o", scope, clinic, department, from_, to, "placed_at")
        where = (where + " and " if where else "where ") + "o.placed_at is not null"
        measures = (
            "count(*) as placed, count(o.turnaround_minutes) as resulted, "
            "count(*) filter (where o.status = 'cancelled') as cancelled, "
            "count(*) filter (where o.status in ('placed', 'accepted')) as pending, "
            "round(median(o.turnaround_minutes), 1)::double as median_minutes, "
            "round(quantile_cont(o.turnaround_minutes, 0.9), 1)::double as p90_minutes"
        )
        columns = ", ".join(_OPS_GROUPS[k] for k in keys)
        positions = ", ".join(str(i + 1) for i in range(len(keys)))
        sql = (
            f"select {columns + ', ' if keys else ''}{measures} from main.fact_order o {where}"
            + (f" group by {positions} order by {positions}" if keys else "")
        )
        return query(sql, params)

    @app.get("/api/operations/lab-volumes")
    def lab_volumes(
        scope: Annotated[Scope, Depends(current_scope)],
        group_by: Annotated[str, Query(alias="groupBy")] = "month",
    ) -> list[dict[str, Any]]:
        """The legacy lab's history from LabFlow's warehouse: results, visits, abnormal and critical
        results and mean turnaround (days), by `month`, `test` or `payer`. Its months are shifted by
        up to 180 days (de-identified). The whole lab: group users only. Empty when not read."""
        if not scope.group:
            raise HTTPException(403, "Lab volumes are for the group permission.")
        keys = {"month": "month", "test": "test_name, loinc_code", "payer": "payer_type"}
        if group_by not in keys:
            raise HTTPException(422, f"groupBy must be one of: {', '.join(keys)}")
        columns = keys[group_by]
        sql = (
            f"select {columns}, sum(results)::bigint as results, sum(visits)::bigint as visits, "
            "sum(abnormal)::bigint as abnormal, sum(critical)::bigint as critical, "
            "round(sum(turnaround_days_sum) / nullif(sum(turnaround_count), 0), 2)::double "
            "as turnaround_mean_days "
            f"from main.mart_lab_volume_monthly group by {columns} order by "
            + ("month" if group_by == "month" else "results desc, " + columns)
        )
        return query(sql, [])

    @app.get("/api/operations/cancellations")
    def cancellations(
        scope: Annotated[Scope, Depends(current_scope)],
        clinic: str | None = None,
        department: str | None = None,
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Per month and department: orders placed, cancelled, and cancels the lab refused."""
        o_where, o_params = ops_clauses("o", scope, clinic, department, from_, to, "placed_at")
        o_where = (o_where + " and " if o_where else "where ") + "o.placed_at is not null"
        c_where, c_params = ops_clauses("e", scope, clinic, None, from_, to, "occurred_at")
        c_where = (c_where + " and " if c_where else "where ") + (
            "e.type in ('order.cancelled', 'order.cancel-refused')"
        )
        dept = "and coalesce(f.department, 'Unknown') = ?" if department else ""
        sql = (
            "with placed as (select date_trunc('month', o.placed_at)::date as month, o.department, "
            f"count(*) as placed from main.fact_order o {o_where} group by 1, 2), "
            "cancels as (select date_trunc('month', e.occurred_at)::date as month, "
            "coalesce(f.department, 'Unknown') as department, "
            "count(*) filter (where e.type = 'order.cancelled') as cancelled, "
            "count(*) filter (where e.type = 'order.cancel-refused') as cancel_refused "
            "from main.stg_clinical_event e left join main.fact_order f "
            "on f.clinic_slug = e.clinic_slug and f.order_id = e.order_id "
            f"{c_where} {dept} group by 1, 2) "
            "select coalesce(p.month, c.month) as month, "
            "coalesce(p.department, c.department) as department, "
            "coalesce(p.placed, 0) as placed, coalesce(c.cancelled, 0) as cancelled, "
            "coalesce(c.cancel_refused, 0) as cancel_refused "
            "from placed p full outer join cancels c "
            "on c.month = p.month and c.department = p.department "
            "order by 1, 2"
        )
        return query(sql, [*o_params, *c_params, *([department] if department else [])])

    @app.get("/api/finance/revenue")
    def revenue(
        scope: Annotated[Scope, Depends(current_scope)],
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
        positions = ", ".join(str(i + 1) for i in range(len(keys)))
        where, params = _filters("r", scope, business, from_, to)
        sql = (
            f"select {columns}, round(sum(r.revenue), 2)::double as revenue "
            "from main.mart_revenue_monthly r join main.dim_business b using (business_id) "
            f"{where} group by {positions} order by {positions}"
        )
        return query(sql, params)

    @app.get("/api/finance/ohip-collection")
    def ohip_collection(
        scope: Annotated[Scope, Depends(current_scope)],
        business: str | None = None,
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _filters("r", scope, business, from_, to)
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

    @app.get("/api/finance/ohip-providers")
    def ohip_providers(
        scope: Annotated[Scope, Depends(current_scope)],
        business: str | None = None,
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
    ) -> list[dict[str, Any]]:
        """OHIP billed (journal), short-paid and refused per provider over the range."""
        where, params = _filters("r", scope, business, from_, to)
        sql = (
            "select r.provider_code as provider, "
            "round(sum(r.billed), 2)::double as billed, "
            "round(sum(r.short_paid), 2)::double as short_paid, "
            "round(sum(r.refused), 2)::double as refused, "
            "(case when sum(r.billed) > 0 "
            "then round(sum(r.short_paid) / sum(r.billed), 4) end)::double as short_paid_rate, "
            "(case when sum(r.billed) > 0 "
            "then round(sum(r.refused) / sum(r.billed), 4) end)::double as refused_rate "
            "from main.mart_ohip_provider_monthly r "
            f"{where} group by 1 order by 2 desc, 1"
        )
        return query(sql, params)

    @app.get("/api/finance/hst")
    def hst(
        scope: Annotated[Scope, Depends(current_scope)],
        business: str | None = None,
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Sales, purchases, tax collected and ITCs by month and tax code (see mart_hst_period)."""
        where, params = _filters("r", scope, business, from_, to)
        sql = (
            'select r.month, r.tax_code as "taxCode", r.tax_name as "taxName", '
            'r.rate_percent::double as "ratePercent", r.measure, '
            "round(sum(r.amount), 2)::double as amount "
            f"from main.mart_hst_period r {where} "
            "group by 1, 2, 3, 4, 5 order by 1, 5, 2"
        )
        return query(sql, params)

    @app.get("/api/finance/aging")
    def aging(
        scope: Annotated[Scope, Depends(current_scope)],
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
        clauses, filter_params = _business_clauses("s", scope, business)
        where = "".join(f" and {c}" for c in clauses)
        sql = (
            "with latest as (select max(snapshot_date) as d from main.fact_open_item_snapshot "
            f"where side = ?{cte_extra}) "
            "select b.code as business, p.party_type, s.aging_bucket, s.snapshot_date, "
            "round(sum(s.balance), 2)::double as balance, count(*) as items "
            "from main.fact_open_item_snapshot s join latest on s.snapshot_date = latest.d "
            "join main.dim_business b on b.business_id = s.business_id "
            "join main.dim_party p on p.party_id = s.party_id "
            f"where s.side = ?{where} "
            "group by 1, 2, 3, 4 order by 1, 2, 3"
        )
        return query(sql, [*cte_params, side, *filter_params])

    @app.get("/api/meta/runs")
    def runs(
        scope: Annotated[Scope, Depends(current_scope)],
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ) -> list[dict[str, Any]]:
        """The latest `analytics run` reports, newest first: steps, row counts against the last good
        run, dbt tests that did not pass, warnings. The whole warehouse: group users only."""
        if not scope.group:
            raise HTTPException(403, "Run reports are for the group permission.")
        return load_reports(config)[:limit]

    @app.get("/api/finance/ohip-anomalies")
    def ohip_anomalies(
        scope: Annotated[Scope, Depends(current_scope)],
        business: str | None = None,
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Provider-months whose short-paid or refused rate is far above the provider's own earlier
        months (latest `analytics score` run), with the numbers behind each flag. Empty before the
        first run."""
        run = latest_run()
        if run is None:
            return []
        where, params = _filters("s", scope, business, from_, to)
        where = (where + " and " if where else "where ") + "s.run_id = ? and s.flagged"
        sql = (
            "select b.code as business, s.provider, s.month, s.measure, s.billed, s.amount, "
            "round(s.rate, 4) as rate, round(s.usual_rate, 4) as usual_rate, "
            "round(s.spread, 4) as spread, round(s.z, 1) as z, "
            "s.above_any_spread as above_steady_history, s.history_months "
            "from ml.remittance_score s join main.dim_business b using (business_id) "
            f"{where} order by s.month desc, b.code, s.provider, s.measure"
        )
        return query(sql, [*params, run["runId"]])

    @app.get("/api/models/revenue-forecast")
    def revenue_forecast(
        scope: Annotated[Scope, Depends(models_scope)],
        business: str | None = None,
    ) -> dict[str, Any]:
        """The latest run's revenue series in the caller's scope: status, the chosen model, every
        candidate's backtest, the months used and the next six months with a rough band."""
        run = latest_run()
        if run is None:
            return {"run": None, "series": []}
        rid = run["runId"]
        where, params = _filters("f", scope, business, None, None)
        where = (where + " and " if where else "where ") + "f.run_id = ?"
        series = query(
            "select f.business_id, b.code as business, b.name as business_name, "
            "f.line_of_business, f.status, f.model, f.months, f.first_month "
            "from ml.forecast_series f join main.dim_business b using (business_id) "
            f"{where} order by b.code, f.line_of_business",
            [*params, rid],
        )
        if not series:
            return {"run": run, "series": []}
        ids = sorted({s["business_id"] for s in series})
        marks = ", ".join("?" for _ in ids)
        tests = query(
            "select business_id, line_of_business, model, origins, horizon, round(mae, 2) as mae, "
            "round(mape, 1) as mape, round(mase, 3) as mase, chosen from ml.backtest "
            f"where run_id = ? and business_id in ({marks}) order by mase nulls last, model",
            [rid, *ids],
        )
        ahead = query(
            "select business_id, line_of_business, month, round(forecast, 2) as forecast, "
            "round(lower, 2) as lower, round(upper, 2) as upper from ml.forecast "
            f"where run_id = ? and business_id in ({marks}) order by month",
            [rid, *ids],
        )
        history = query(
            "select business_id, line_of_business, month, "
            "round(sum(revenue), 2)::double as revenue "
            f"from main.mart_revenue_monthly where business_id in ({marks}) and month <= ? "
            "group by 1, 2, 3 order by 3",
            [*ids, run["dataThrough"]],
        )

        def of(rows: list[dict[str, Any]], s: dict[str, Any]) -> list[dict[str, Any]]:
            key = (s["business_id"], s["line_of_business"])
            return [
                {k: v for k, v in r.items() if k not in ("business_id", "line_of_business")}
                for r in rows
                if (r["business_id"], r["line_of_business"]) == key
            ]

        return {
            "run": run,
            "series": [
                {
                    **{k: v for k, v in s.items() if k != "business_id"},
                    "backtests": of(tests, s),
                    "history": of(history, s),
                    "forecast": of(ahead, s),
                }
                for s in series
            ],
        }

    return app


def _business_clauses(
    alias: str, scope: Scope, business: str | None
) -> tuple[list[str], list[Any]]:
    """The clinic in the token always applies; a `business` in the request narrows it further, so
    asking for another clinic gives an empty answer, not that clinic's numbers."""
    clauses: list[str] = []
    params: list[Any] = []
    if not scope.group:
        clauses.append(_SCOPE_FILTER.format(a=alias))
        params.append(scope.clinic_slug)
    if business:
        clauses.append(_BUSINESS_FILTER.format(a=alias))
        params += [business, business]
    return clauses, params


def _filters(
    alias: str, scope: Scope, business: str | None, from_: date | None, to: date | None
) -> tuple[str, list[Any]]:
    clauses, params = _business_clauses(alias, scope, business)
    if from_:
        clauses.append(f"{alias}.month >= date_trunc('month', ?::date)")
        params.append(from_)
    if to:
        clauses.append(f"{alias}.month <= ?::date")
        params.append(to)
    return (("where " + " and ".join(clauses)) if clauses else ""), params


app = create_app()
