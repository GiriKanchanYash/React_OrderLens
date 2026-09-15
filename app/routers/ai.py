from fastapi import APIRouter, Depends

from app.auth import require_roles
from app.services import ai_service as svc

router = APIRouter(prefix="/api/ai", tags=["AI"])


@router.get("/copilot/quick-analyses")
def quick_analyses():
    return svc.quick_analyses()


@router.post("/copilot/run-analysis")
def run_analysis(body: dict):
    return svc.run_analysis(body.get("key") or "")


@router.post("/copilot/chat")
def copilot_chat(body: dict):
    return svc.copilot_chat(
        body.get("question") or body.get("message") or "",
        body.get("persona") or "sales_ops",
    )


@router.get("/copilot/saved-insights")
def saved_insights(persona: str | None = None):
    return svc.saved_insights(persona)


@router.post("/copilot/save-insight")
def save_insight(body: dict, _=Depends(require_roles("admin", "sales_ops", "planning", "exec"))):
    return svc.save_insight(body)


@router.post("/copilot/delete-insight")
def delete_insight(body: dict, _=Depends(require_roles("admin", "sales_ops", "planning", "exec"))):
    return svc.delete_insight(int(body.get("insight_id") or 0))


@router.get("/copilot/frequent-questions")
def frequent_questions(persona: str | None = None):
    return svc.frequent_questions(persona)


@router.get("/copilot/most-frequent")
def most_frequent():
    return svc.most_frequent()


@router.get("/fulfillment-agent/queue")
def fulfillment_queue(limit: int = 50):
    return svc.fulfillment_queue(limit)


@router.post("/fulfillment-agent/recommend")
def fulfillment_recommend(body: dict, _=Depends(require_roles("admin", "sales_ops", "planning"))):
    return svc.recommend("fulfillment", body)


@router.get("/inventory-agent/queue")
def inventory_queue(limit: int = 50):
    return svc.inventory_queue(limit)


@router.post("/inventory-agent/recommend")
def inventory_recommend(body: dict, _=Depends(require_roles("admin", "sales_ops", "planning"))):
    return svc.recommend("inventory", body)


@router.get("/forecast-agent/queue")
def forecast_queue(limit: int = 50):
    return svc.forecast_queue(limit)


@router.post("/forecast-agent/recommend")
def forecast_recommend(body: dict, _=Depends(require_roles("admin", "sales_ops", "planning"))):
    return svc.recommend("forecast", body)


@router.post("/agent/mark-reviewed")
def mark_reviewed(body: dict, user=Depends(require_roles("admin", "sales_ops", "planning"))):
    return svc.mark_reviewed(
        body.get("agent_key") or "fulfillment",
        body.get("entity_id") or "",
        body.get("entity_type") or "order",
        body.get("notes") or "",
        user.name,
        body.get("action_taken") or "MARK_REVIEWED",
    )
