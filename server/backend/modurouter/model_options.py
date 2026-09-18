"""UI choices reuse the router's price, freshness and allowlist checks."""
from .errors import AppError


def low_efforts(provider: str, model: str, raw: dict) -> list[str]:
    if provider == "openai" and model == "openai/gpt-5-nano":
        return ["minimal", "low"]
    # Only advertise controls that the provider catalog declares.
    if provider == "openrouter" and "reasoning" in raw.get("supported_parameters", []):
        declared = raw.get("supported_efforts")
        return [v for v in ("minimal", "low") if v in declared] if isinstance(declared, list) else ["low"]
    return []


def select_routes(choices, model: str | None, effort: str | None):
    result = []
    for route in choices:
        if model and route.model_id != model:
            continue
        supported = low_efforts(route.provider_code, route.model_id, route.price_data)
        if effort and supported and effort not in supported:
            continue
        result.append(route)
    if not result:
        raise AppError("NO_ELIGIBLE_MODEL", "선택한 모델과 사고 강도를 현재 가격 조건에서 사용할 수 없습니다.", 503, True)
    return result


def effective_effort(route, requested: str | None):
    supported = low_efforts(route.provider_code, route.model_id, route.price_data)
    return (requested or supported[0]) if supported else None


def catalog_view(choices):
    models = {}
    for route in choices:
        item = models.setdefault(route.model_id, {"id": route.model_id,
            "name": route.model_id.split("/", 1)[-1], "providers": [], "efforts": [],
            "input_per_m": str(route.input_per_m), "output_per_m": str(route.output_per_m)})
        item["providers"].append(route.provider_code)
        item["efforts"] = sorted(set(item["efforts"] + low_efforts(route.provider_code, route.model_id, route.price_data)), key=lambda v: ("minimal", "low").index(v))
    return {"models": list(models.values()), "efforts": ["minimal", "low"], "selection_supported": True}
