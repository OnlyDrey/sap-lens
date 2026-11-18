"""Modules router - returns distinct SAP modules for filter options."""
from fastapi import APIRouter
from cache import get_modules
from models import ModuleInfo

router = APIRouter(prefix="/api/modules", tags=["Modules"])


@router.get("", response_model=list[ModuleInfo])
def list_modules() -> list[ModuleInfo]:
    return get_modules()