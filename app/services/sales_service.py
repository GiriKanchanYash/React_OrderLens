from __future__ import annotations

import threading
import time
from typing import Any

from app.db import qcol, qview, run_query

_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 300


def _cache_get(key: str) -> Any | None:
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        ts, val = item
        if time.time() - ts > _CACHE_TTL:
            _CACHE.pop(key, None)
            return None
        return val


def _cache_set(key: str, val: Any) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), val)


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _num(row: dict, *keys: str, default: float = 0.0) -> float:
    for k in keys:
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                continue
    return default


def _str(row: dict, *keys: str, default: str = "") -> str:
    for k in keys:
        if k in row and row[k] is not None:
            return str(row[k])
    return default


def get_filters() -> dict:
    cached = _cache_get("filters")
    if cached is not None:
        return cached
    countries = run_query(f'''
        select distinct {qcol("country_code")} as country_code
        from {qview("customer_profile")}
        where {qcol("country_code")} is not null
        order by 1
        OFFSET 0 ROWS FETCH NEXT 200 ROWS ONLY
    ''')
    categories = run_query(f'''
        select distinct {qcol("sales_order_category")} as category
        from {qview("orders_header_summary")}
        where {qcol("sales_order_category")} is not null
        order by 1
    ''')
    statuses = run_query(f'''
        select distinct {qcol("overall_order_status")} as status
        from {qview("orders_header_summary")}
        where {qcol("overall_order_status")} is not null
        order by 1
    ''')
    dealers = run_query(f'''
        select {qcol("dealer_key", "dealer_order_performance")} as dealer_id,
               {qcol("dealer_name", "dealer_order_performance")} as dealer_name
        from {qview("dealer_order_performance")}
        order by {qcol("total_order_value", "dealer_order_performance")} desc
        OFFSET 0 ROWS FETCH NEXT 500 ROWS ONLY
    ''')
    result = {
        "countries": [_str(r, "country_code") for r in countries],
        "categories": [_str(r, "category") for r in categories],
        "statuses": [_str(r, "status") for r in statuses],
        "dealers": [
            {"dealer_id": _str(r, "dealer_id"), "dealer_name": _str(r, "dealer_name")}
            for r in dealers
        ],
    }
    _cache_set("filters", result)
    return result


def get_summary(country: str | None = None, category: str | None = None) -> dict:
    cache_key = f"summary:{country or 'all'}:{category or 'all'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    cf = f''' and {qcol("customer_country")} = '{country.replace("'", "''")}' ''' if country else ""
    catf = f''' and {qcol("sales_order_category")} = '{category.replace("'", "''")}' ''' if category else ""

    order_kpis = run_query(f'''
        select
            count(*) as order_count,
            coalesce(sum({qcol("total_order_value")}), 0) as order_value,
            SUM(CASE WHEN {qcol("overall_order_status")} = 'Fulfilled' THEN 1 ELSE 0 END) as fulfilled_count,
            SUM(CASE WHEN {qcol("overall_order_status")} = 'Open' THEN 1 ELSE 0 END) as open_count,
            SUM(CASE WHEN {qcol("delivery_blocked")} = 'Y' THEN 1 ELSE 0 END) as delivery_blocked,
            SUM(CASE WHEN {qcol("billing_blocked")} = 'Y' THEN 1 ELSE 0 END) as billing_blocked,
            SUM(CASE WHEN {qcol("credit_blocked")} = 'Y' THEN 1 ELSE 0 END) as credit_blocked
        from {qview("orders_header_summary")}
        where 1=1 {cf} {catf}
    ''')
    o = order_kpis[0] if order_kpis else {}

    backlog = run_query(f'''
        select
            count(distinct {qcol("sales_order_id")}) as backlog_orders,
            coalesce(sum({qcol("open_value")}), 0) as backlog_value,
            coalesce(avg({qcol("order_age_days")}), 0) as avg_age_days
        from {qview("orders_backlog_analysis")}
    ''')
    b = backlog[0] if backlog else {}

    inv = run_query(f'''
        select
            count(*) as breach_count,
            coalesce(sum({qcol("reorder_shortage_quantity")}), 0) as shortage_qty
        from {qview("inventory_reorder_point_breaches")}
    ''')
    i = inv[0] if inv else {}

    from datetime import date as _date
    current_period = f"{_date.today().year}{_date.today().month:02d}"

    # Mart "accuracy" is fill rate (actual/forecast). Averaging all rows including future /
    # unmatched material-plant combos collapses to ~0%. Prefer closed periods with actuals.
    fc = run_query(f'''
        select
            avg(case
                when {qcol("forecast_period")} <= %s
                 and {qcol("total_actual_sales_quantity")} > 0
                then {qcol("forecast_accuracy_percent")}
            end) as avg_accuracy_matched,
            avg(case
                when {qcol("forecast_period")} <= %s
                 and {qcol("total_actual_sales_quantity")} > 0
                then {qcol("absolute_percentage_error")}
            end) as avg_mape_matched,
            avg(case
                when {qcol("forecast_period")} <= %s
                then CASE WHEN 100 - {qcol("absolute_percentage_error")} > 0
                          THEN 100 - {qcol("absolute_percentage_error")} ELSE 0 END
            end) as classic_accuracy_closed,
            SUM(CASE WHEN {qcol("forecast_period")} <= %s THEN 1 ELSE 0 END) as closed_rows,
            SUM(CASE WHEN 
                {qcol("forecast_period")} <= %s
                and {qcol("total_actual_sales_quantity")} > 0
             THEN 1 ELSE 0 END) as matched_rows,
            count(*) as forecast_rows
        from {qview("forecasting_accuracy_by_material_plant_period")}
        where {qcol("forecast_accuracy_percent")} is not null
    ''', (current_period, current_period, current_period, current_period, current_period))
    f = fc[0] if fc else {}

    outliers = run_query(f'''
        select count(*) as outlier_count
        from {qview("forecasting_outlier_analysis")}
        where {qcol("variance_category")} <> 'Normal'
          and {qcol("forecast_period")} <= %s
    ''', (current_period,))
    out = outliers[0] if outliers else {}

    dealer = run_query(f'''
        select
            count(*) as dealer_count,
            coalesce(sum({qcol("total_order_value", "dealer_order_performance")}), 0) as dealer_order_value,
            coalesce(sum({qcol("fulfilled_orders", "dealer_order_performance")}), 0) as dealer_fulfilled,
            coalesce(sum({qcol("total_orders", "dealer_order_performance")}), 0) as dealer_orders
        from {qview("dealer_order_performance")}
    ''')
    d = dealer[0] if dealer else {}

    order_count = _num(o, "order_count")
    fulfilled = _num(o, "fulfilled_count")
    fulfillment_rate = round(100.0 * fulfilled / order_count, 1) if order_count else 0.0
    dealer_orders = _num(d, "dealer_orders")
    dealer_fulfilled = _num(d, "dealer_fulfilled")
    dealer_fulfillment = round(100.0 * dealer_fulfilled / dealer_orders, 1) if dealer_orders else 0.0

    status_chart = run_query(f'''
        select {qcol("overall_order_status")} as label, count(*) as value
        from {qview("orders_header_summary")}
        where 1=1 {cf} {catf}
        group by {qcol("overall_order_status")} order by 2 desc
    ''')
    category_chart = run_query(f'''
        select {qcol("sales_order_category")} as label, coalesce(sum({qcol("total_order_value")}), 0) as value
        from {qview("orders_header_summary")}
        where 1=1 {cf}
        group by {qcol("sales_order_category")} order by 2 desc
    ''')
    trend_chart = run_query(f'''
        select CONVERT(VARCHAR(10), {qcol("order_date")}, 120) as period, count(*) as value
        from {qview("orders_header_summary")}
        where {qcol("order_date")} is not null {cf} {catf}
        group by CONVERT(VARCHAR(10), {qcol("order_date")}, 120)
        order by 1 desc
        OFFSET 0 ROWS FETCH NEXT 12 ROWS ONLY
    ''')
    trend_chart = list(reversed(trend_chart))

    result = {
        "kpis": {
            "order_count": order_count,
            "order_value": _num(o, "order_value"),
            "fulfillment_rate": fulfillment_rate,
            "open_orders": _num(o, "open_count"),
            "backlog_orders": _num(b, "backlog_orders"),
            "backlog_value": _num(b, "backlog_value"),
            "avg_backlog_age_days": round(_num(b, "avg_age_days"), 1),
            "reorder_breaches": _num(i, "breach_count"),
            "shortage_qty": _num(i, "shortage_qty"),
            "forecast_accuracy": round(_num(f, "avg_accuracy_matched"), 1),
            "forecast_mape": round(_num(f, "avg_mape_matched"), 1),
            "forecast_classic_accuracy": round(_num(f, "classic_accuracy_closed"), 1),
            "forecast_matched_rows": int(_num(f, "matched_rows")),
            "forecast_closed_rows": int(_num(f, "closed_rows")),
            "forecast_coverage_pct": round(
                100.0 * _num(f, "matched_rows") / _num(f, "closed_rows"), 1
            ) if _num(f, "closed_rows") else 0.0,
            "forecast_outliers": _num(out, "outlier_count"),
            "forecast_current_period": current_period,
            "delivery_blocked": _num(o, "delivery_blocked"),
            "billing_blocked": _num(o, "billing_blocked"),
            "credit_blocked": _num(o, "credit_blocked"),
            "dealer_count": _num(d, "dealer_count"),
            "dealer_fulfillment_rate": dealer_fulfillment,
        },
        "charts": {
            "orders_by_status": [
                {"label": _str(r, "label"), "value": _num(r, "value")} for r in status_chart
            ],
            "value_by_category": [
                {"label": _str(r, "label"), "value": _num(r, "value")} for r in category_chart
            ],
            "order_trend": [
                {"period": _str(r, "period")[:10], "value": _num(r, "value")} for r in trend_chart
            ],
        },
        "as_of": time.strftime("%Y-%m-%d %H:%M"),
    }
    _cache_set(cache_key, result)
    return result


def get_orders(
    status: str | None = None,
    category: str | None = None,
    country: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    wh = ["1=1"]
    if status:
        wh.append(f'''{qcol("overall_order_status")} = '{status.replace("'", "''")}' ''')
    if category:
        wh.append(f'''{qcol("sales_order_category")} = '{category.replace("'", "''")}' ''')
    if country:
        wh.append(f'''{qcol("customer_country")} = '{country.replace("'", "''")}' ''')
    where = " and ".join(wh)
    rows = run_query(f'''
        select
            {qcol("sales_order_id")} as sales_order_id,
            {qcol("customer_name")} as customer_name,
            {qcol("customer_type")} as customer_type,
            {qcol("customer_country")} as customer_country,
            {qcol("sales_order_category")} as sales_order_category,
            {qcol("order_date")} as order_date,
            {qcol("total_order_value")} as total_order_value,
            {qcol("net_order_value")} as net_order_value,
            {qcol("overall_order_status")} as overall_order_status,
            {qcol("delivery_blocked")} as delivery_blocked,
            {qcol("billing_blocked")} as billing_blocked,
            {qcol("credit_blocked")} as credit_blocked,
            {qcol("requested_delivery_date")} as requested_delivery_date
        from {qview("orders_header_summary")}
        where {where}
        order by {qcol("order_date")} desc
        OFFSET {int(offset)} ROWS FETCH NEXT {int(limit)} ROWS ONLY
    ''')
    return {
        "rows": [
            {
                "sales_order_id": _str(r, "sales_order_id"),
                "customer_name": _str(r, "customer_name"),
                "customer_type": _str(r, "customer_type"),
                "customer_country": _str(r, "customer_country"),
                "sales_order_category": _str(r, "sales_order_category"),
                "order_date": _str(r, "order_date")[:10],
                "total_order_value": _num(r, "total_order_value"),
                "net_order_value": _num(r, "net_order_value"),
                "overall_order_status": _str(r, "overall_order_status"),
                "delivery_blocked": _str(r, "delivery_blocked"),
                "billing_blocked": _str(r, "billing_blocked"),
                "credit_blocked": _str(r, "credit_blocked"),
                "requested_delivery_date": _str(r, "requested_delivery_date")[:10],
            }
            for r in rows
        ]
    }


def get_order_detail(order_id: str) -> dict:
    safe = order_id.replace("'", "''")
    header = run_query(f'''
        select TOP 1 * from {qview("orders_header_summary")}
        where {qcol("sales_order_id")} = '{safe}'
    ''')
    lines = run_query(f'''
        select * from {qview("orders_line_detail")}
        where {qcol("sales_order_id")} = '{safe}'
        order by {qcol("sales_order_item_number")}
    ''')
    flow = run_query(f'''
        select * from {qview("orders_document_flow_tracking")}
        where {qcol("sales_order_id", "orders_document_flow_tracking")} = '{safe}'
        order by {qcol("document_flow_date", "orders_document_flow_tracking")}
    ''')
    schedule = run_query(f'''
        select * from {qview("orders_fulfillment_schedule")}
        where {qcol("sales_order_id")} = '{safe}'
        order by {qcol("schedule_line_number")}
    ''')
    h = header[0] if header else {}
    return {
        "header": {k: (str(v) if v is not None else None) for k, v in h.items()},
        "lines": lines,
        "document_flow": flow,
        "schedule": schedule,
    }


def get_customer_health(status: str | None = None, limit: int = 100) -> dict:
    wh = "1=1"
    if status:
        wh = f'''{qcol("customer_status")} = '{status.replace("'", "''")}' '''
    rows = run_query(f'''
        select
            r.{qcol("customer_key")} as customer_key,
            r.{qcol("customer_name")} as customer_name,
            r.{qcol("customer_type")} as customer_type,
            r.{qcol("customer_status")} as customer_status,
            r.{qcol("days_since_last_order")} as days_since_last_order,
            r.{qcol("total_orders")} as total_orders,
            r.{qcol("orders_per_year")} as orders_per_year,
            coalesce(v.{qcol("lifetime_value")}, 0) as lifetime_value,
            coalesce(v.{qcol("avg_order_value")}, 0) as avg_order_value
        from {qview("customer_recency_frequency")} r
        left join {qview("customer_lifetime_value")} v
          on r.{qcol("customer_key")} = v.{qcol("customer_key")}
        where {wh}
        order by lifetime_value desc
        OFFSET 0 ROWS FETCH NEXT {int(limit)} ROWS ONLY
    ''')
    summary = run_query(f'''
        select
            SUM(CASE WHEN {qcol("customer_status")} = 'Active' THEN 1 ELSE 0 END) as active_count,
            SUM(CASE WHEN {qcol("customer_status")} = 'At Risk' THEN 1 ELSE 0 END) as at_risk_count,
            SUM(CASE WHEN {qcol("customer_status")} = 'Inactive' THEN 1 ELSE 0 END) as inactive_count,
            avg({qcol("days_since_last_order")}) as avg_days_since
        from {qview("customer_recency_frequency")}
    ''')
    s = summary[0] if summary else {}
    at_risk_rows = [r for r in rows if _str(r, "customer_status") == "At Risk"]
    top_at_risk = sorted(
        [
            {
                "customer_key": _str(r, "customer_key"),
                "customer_name": _str(r, "customer_name"),
                "days_since_last_order": _num(r, "days_since_last_order"),
                "lifetime_value": _num(r, "lifetime_value"),
            }
            for r in at_risk_rows
        ],
        key=lambda x: x["lifetime_value"],
        reverse=True,
    )[:5]

    return {
        "summary": {
            "active": _num(s, "active_count"),
            "at_risk": _num(s, "at_risk_count"),
            "inactive": _num(s, "inactive_count"),
            "avg_days_since_last_order": round(_num(s, "avg_days_since"), 1),
        },
        "insights": {
            "headline": (
                f"{int(_num(s, 'at_risk_count'))} customers are At Risk and "
                f"{int(_num(s, 'inactive_count'))} are Inactive — prioritize high-CLV outreach."
            ),
            "top_at_risk": top_at_risk,
            "recommended_actions": [
                "Call / visit At Risk customers with highest CLV this week.",
                "Log outreach notes so the team knows who was contacted.",
                "Review Inactive accounts for win-back offers or account closure.",
                "Watch days-since-last-order rising above your sales cadence SLA.",
            ],
        },
        "rows": [
            {
                "customer_key": _str(r, "customer_key"),
                "customer_name": _str(r, "customer_name"),
                "customer_type": _str(r, "customer_type"),
                "customer_status": _str(r, "customer_status"),
                "days_since_last_order": _num(r, "days_since_last_order"),
                "total_orders": _num(r, "total_orders"),
                "orders_per_year": round(_num(r, "orders_per_year"), 2),
                "lifetime_value": _num(r, "lifetime_value"),
                "avg_order_value": _num(r, "avg_order_value"),
            }
            for r in rows
        ],
    }


def get_inventory_overview(limit: int = 100) -> dict:
    plants = run_query(f'''
        select
            {qcol("plant_key")} as plant_key,
            {qcol("plant_name")} as plant_name,
            {qcol("country_code")} as country_code,
            {qcol("total_materials_managed")} as total_materials,
            {qcol("materials_below_reorder_point")} as below_reorder,
            {qcol("materials_below_safety_stock")} as below_safety,
            {qcol("total_unrestricted_stock")} as unrestricted_stock
        from {qview("inventory_plant_summary")}
        order by {qcol("materials_below_reorder_point")} desc
        OFFSET 0 ROWS FETCH NEXT 50 ROWS ONLY
    ''')
    breaches = run_query(f'''
        select
            {qcol("material_key")} as material_key,
            {qcol("material_description")} as material_description,
            {qcol("plant_name")} as plant_name,
            {qcol("unrestricted_stock_quantity")} as stock_qty,
            {qcol("reorder_point_quantity")} as reorder_point,
            {qcol("reorder_shortage_quantity")} as shortage_qty,
            {qcol("planned_delivery_days")} as planned_delivery_days
        from {qview("inventory_reorder_point_breaches")}
        order by {qcol("reorder_shortage_quantity")} desc
        OFFSET 0 ROWS FETCH NEXT {int(limit)} ROWS ONLY
    ''')
    total_shortage = sum(_num(b, "shortage_qty") for b in breaches)
    zero_stock = sum(1 for b in breaches if _num(b, "stock_qty") <= 0)
    return {
        "plants": plants,
        "breaches": breaches,
        "insights": {
            "headline": (
                f"{len(breaches)} reorder breaches · shortage qty {total_shortage:,.0f} · "
                f"{zero_stock} at zero stock."
            ),
            "recommended_actions": [
                "Open Agent Workbench > Inventory and clear Act now shortages first.",
                "Raise purchase / STO for top shortage materials today.",
                "Confirm lead times with buyers before promising customer dates.",
                "Check alternate plants for transfer when local stock is zero.",
            ],
        },
    }


def get_forecast_overview(limit: int = 100) -> dict:
    from datetime import date

    current_period = f"{date.today().year}{date.today().month:02d}"

    trend = run_query(f'''
        select
            {qcol("forecast_period")} as period,
            avg({qcol("avg_accuracy_percent")}) as accuracy,
            avg({qcol("avg_absolute_percentage_error")}) as mape,
            sum({qcol("total_forecast_quantity")}) as forecast_qty,
            sum({qcol("total_actual_quantity")}) as actual_qty
        from {qview("forecasting_trend_analysis")}
        group by {qcol("forecast_period")}
        order by 1 desc
        OFFSET 0 ROWS FETCH NEXT 12 ROWS ONLY
    ''')
    outliers = run_query(f'''
        select
            {qcol("material_key")} as material_key,
            {qcol("material_description")} as material_description,
            {qcol("plant_name")} as plant_name,
            {qcol("forecast_period")} as forecast_period,
            {qcol("variance_category")} as variance_category,
            {qcol("absolute_percentage_error")} as ape,
            {qcol("forecast_quantity")} as forecast_qty,
            {qcol("actual_sales_quantity")} as actual_qty
        from {qview("forecasting_outlier_analysis")}
        where {qcol("variance_category")} <> 'Normal'
          and {qcol("forecast_period")} <= %s
        order by {qcol("absolute_percentage_error")} desc
        OFFSET 0 ROWS FETCH NEXT {int(limit)} ROWS ONLY
    ''', (current_period,))
    # Method rollup. NOTE: the original Snowflake version first tries a raw
    # BASE_LAYER join for a more precise per-material accuracy calc, falling
    # back to forecasting_method_performance only if that returns no rows.
    # BASE_LAYER doesn't exist in this Fabric setup (flat tables loaded
    # directly from CSV exports), so this always uses the mart-level rollup.
    methods = run_query(f'''
        select
            {qcol("forecast_method_code")} as method,
            avg({qcol("avg_accuracy_percent")}) as accuracy,
            avg({qcol("avg_absolute_percentage_error")}) as mape,
            sum({qcol("forecast_count")}) as forecast_count
        from {qview("forecasting_method_performance")}
        group by {qcol("forecast_method_code")}
            order by 2 desc
        ''')

    # Open / forward demand plan by period (qty), which is meaningful even before actuals land
    plan_trend = run_query(f'''
        select
            {qcol("forecast_period")} as period,
            sum({qcol("total_forecast_quantity")}) as forecast_qty,
            sum({qcol("total_actual_quantity")}) as actual_qty,
            count(*) as row_count
        from {qview("forecasting_trend_analysis")}
        group by {qcol("forecast_period")}
        order by 1
        OFFSET 0 ROWS FETCH NEXT 18 ROWS ONLY
    ''')

    # Top upcoming forecast commitments (future periods) — actionable for planning
    open_plan = run_query(f'''
        select
            {qcol("material_key")} as material_key,
            {qcol("material_description")} as material_description,
            {qcol("plant_name")} as plant_name,
            {qcol("forecast_period")} as forecast_period,
            {qcol("forecast_method_code")} as forecast_method,
            {qcol("forecast_quantity")} as forecast_qty,
            {qcol("actual_sales_quantity")} as actual_qty
        from {qview("forecasting_outlier_analysis")}
        where {qcol("forecast_period")} > %s
        order by {qcol("forecast_quantity")} desc
        OFFSET 0 ROWS FETCH NEXT {int(limit)} ROWS ONLY
    ''', (current_period,))

    future_periods = [r for r in plan_trend if str(r.get("period") or "") > current_period]
    past_periods = [r for r in plan_trend if str(r.get("period") or "") <= current_period]
    future_only = len(past_periods) == 0 and len(future_periods) > 0

    with_sales = [o for o in outliers if _num(o, "actual_qty") > 0]
    zero_sales = [o for o in outliers if _num(o, "actual_qty") <= 0]
    ape_with_sales = [_num(o, "ape") for o in with_sales]
    avg_ape_with_sales = (sum(ape_with_sales) / len(ape_with_sales)) if ape_with_sales else None
    classic_acc = (100.0 - avg_ape_with_sales) if avg_ape_with_sales is not None else None

    trend_out = []
    for r in plan_trend:
        period = str(r.get("period") or "")
        actual = _num(r, "actual_qty")
        forecast = _num(r, "forecast_qty")
        is_future = period > current_period
        classic = None
        if actual > 0 and forecast > 0:
            classic = max(0.0, 100.0 - abs(forecast - actual) / forecast * 100.0)
        trend_out.append({
            "period": period,
            "forecast_qty": forecast,
            "actual_qty": actual,
            "accuracy": classic if classic is not None else (0.0 if is_future else _num(r, "accuracy")),
            "classic_accuracy": classic,
            "fill_rate": (actual / forecast * 100.0) if forecast > 0 else None,
            "has_actuals": actual > 0,
            "is_future": is_future,
        })

    coverage = run_query(f'''
        select
            SUM(CASE WHEN {qcol("forecast_period")} <= %s THEN 1 ELSE 0 END) as closed_rows,
            SUM(CASE WHEN 
                {qcol("forecast_period")} <= %s
                and {qcol("total_actual_sales_quantity")} > 0
             THEN 1 ELSE 0 END) as matched_rows,
            avg(case
                when {qcol("forecast_period")} <= %s
                 and {qcol("total_actual_sales_quantity")} > 0
                then {qcol("forecast_accuracy_percent")}
            end) as fill_matched
        from {qview("forecasting_accuracy_by_material_plant_period")}
    ''', (current_period, current_period, current_period))
    cov = coverage[0] if coverage else {}
    closed_rows = int(_num(cov, "closed_rows"))
    matched_rows = int(_num(cov, "matched_rows"))
    coverage_pct = round(100.0 * matched_rows / closed_rows, 1) if closed_rows else 0.0
    fill_matched = _num(cov, "fill_matched")

    if future_only:
        headline = (
            f"Forecast rows start at future periods (after {current_period}). "
            f"Sales actuals exist through recent closed months, so fill-rate/MAPE stay at 0%/100% "
            f"until those forecast months close. Showing open demand plan instead."
        )
        actions = [
            "Treat this page as the open demand plan (forecast qty by period), not closed-period accuracy.",
            "Open Agent Workbench > Forecast and review high-volume upcoming commitments.",
            "Validate top materials/plants in the upcoming plan with sales ops before S&OP lock.",
            "After a month closes, re-check fill-rate/MAPE for that period.",
        ]
        fill_note = (
            "Mart accuracy is fill rate (actual / forecast). Future periods have no actuals yet, "
            "so fill rate is 0 and MAPE is 100 until the month closes."
        )
    else:
        headline = (
            f"Matched fill rate {fill_matched:.1f}% on {matched_rows:,} of {closed_rows:,} closed-period rows "
            f"({coverage_pct}% coverage). "
            f"{len(zero_sales)} zero-actual outliers · classic accuracy (where sales) "
            f"{(f'{classic_acc:.1f}%' if classic_acc is not None else 'n/a')}."
        )
        actions = [
            "Open Agent Workbench > Forecast and work Act now outliers.",
            "Low coverage usually means forecast material/plant pairs lack matching sales orders — check plant assignment and demand history.",
            "Investigate Zero Sales - Overforecast: true zero demand vs actuals join gap.",
            "Compare method MAPE on matched closed periods and standardize where volume is high.",
        ]
        fill_note = (
            "Command Center / method KPIs use fill rate only where actual sales > 0 on closed periods. "
            "Rows with no matching sales are excluded from the average (otherwise they force ~0%). "
            f"Coverage: {matched_rows:,}/{closed_rows:,} closed rows ({coverage_pct}%)."
        )

    insights = {
        "current_period": current_period,
        "future_only": future_only,
        "headline": headline,
        "fill_rate_note": fill_note,
        "zero_sales_outlier_count": len(zero_sales),
        "with_sales_outlier_count": len(with_sales),
        "avg_ape_where_sales": round(avg_ape_with_sales, 1) if avg_ape_with_sales is not None else None,
        "classic_accuracy_where_sales": round(classic_acc, 1) if classic_acc is not None else None,
        "matched_rows": matched_rows,
        "closed_rows": closed_rows,
        "coverage_pct": coverage_pct,
        "recommended_actions": actions,
    }

    # Prefer open plan rows for the main table when future-only
    display_outliers = open_plan if future_only else outliers
    if future_only:
        for row in display_outliers:
            row["variance_category"] = "Open forecast (no actuals yet)"
            row["ape"] = None

    return {
        "trend": trend_out,
        "outliers": display_outliers,
        "methods": methods,
        "insights": insights,
        "mode": "open_plan" if future_only else "accuracy",
    }


def get_data_version() -> dict:
    rows = run_query(f'''
        select
            (select count(*) from {qview("orders_header_summary")}) as order_cnt,
            (select count(*) from {qview("orders_backlog_analysis")}) as backlog_cnt,
            (select count(*) from {qview("inventory_reorder_point_breaches")}) as breach_cnt,
            (select coalesce(sum({qcol("open_value")}), 0) from {qview("orders_backlog_analysis")}) as backlog_value
    ''')
    r = rows[0] if rows else {}
    version = "|".join([
        str(_num(r, "order_cnt")),
        str(_num(r, "backlog_cnt")),
        str(_num(r, "breach_cnt")),
        str(_num(r, "backlog_value")),
    ])
    return {"version": version, "checked_at": time.time()}