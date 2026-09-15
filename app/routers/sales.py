from fastapi import APIRouter, Query

from app.services import sales_service as svc

router = APIRouter(prefix="/api/sales", tags=["Sales"])


@router.get("/filters")
def filters():
    return svc.get_filters()


@router.get("/summary")
def summary(country: str | None = None, category: str | None = None):
    return svc.get_summary(country, category)


@router.get("/orders")
def orders(
    status: str | None = None,
    category: str | None = None,
    country: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    return svc.get_orders(status, category, country, limit, offset)


@router.get("/orders/{order_id}")
def order_detail(order_id: str):
    return svc.get_order_detail(order_id)


@router.get("/customer-health")
def customer_health(status: str | None = None, limit: int = Query(100, ge=1, le=500)):
    return svc.get_customer_health(status, limit)


@router.get("/inventory")
def inventory(limit: int = Query(100, ge=1, le=500)):
    return svc.get_inventory_overview(limit)


@router.get("/forecast")
def forecast(limit: int = Query(100, ge=1, le=500)):
    return svc.get_forecast_overview(limit)


@router.get("/data-version")
def data_version():
    return svc.get_data_version()


@router.post("/refresh-cache")
def refresh_cache():
    svc.clear_cache()
    return {"ok": True, "message": "API cache cleared", "version": svc.get_data_version()["version"]}
