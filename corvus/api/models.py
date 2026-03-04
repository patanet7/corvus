"""Model discovery and refresh endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from corvus.auth import get_user
from corvus.model_router import ModelRouter

router = APIRouter(prefix="/api/models", tags=["models"])

_model_router: ModelRouter | None = None


def configure(model_router: ModelRouter) -> None:
    """Wire router to the active ModelRouter instance."""
    if not isinstance(model_router, ModelRouter):
        raise TypeError(f"Expected ModelRouter, got {type(model_router).__name__}")
    global _model_router
    _model_router = model_router


def _require_model_router() -> ModelRouter:
    if _model_router is None:
        raise HTTPException(status_code=503, detail="ModelRouter not initialized")
    return _model_router


@router.get("")
async def list_models(user: str = Depends(get_user)):
    """List all available models for frontend model selection."""
    del user
    model_router = _require_model_router()
    return {
        "models": [m.to_dict() for m in model_router.list_available_models()],
        "default_model": model_router.default_model,
    }


@router.post("/refresh")
async def refresh_models(user: str = Depends(get_user)):
    """Re-probe backends and refresh available models."""
    del user
    model_router = _require_model_router()
    model_router.discover_models()
    return {
        "models": [m.to_dict() for m in model_router.list_available_models()],
        "default_model": model_router.default_model,
    }
