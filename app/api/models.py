from typing import Dict, Any

from fastapi import APIRouter, Request

from app.model_registry import get_model_metadata, list_available_models_for_request

router = APIRouter()


@router.get("/models", tags=["models"])
async def list_models(request: Request) -> Dict[str, Any]:
    """
    List available models in OpenAI-compatible format.
    """
    data = []
    for model_id in list_available_models_for_request(request):
        metadata = get_model_metadata(model_id)
        data.append({
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": metadata["model_family"],
            **metadata,
        })

    return {"object": "list", "data": data}
