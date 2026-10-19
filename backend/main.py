"""SAP Role Access Visualizer - FastAPI application entry point."""

import asyncio
import logging
import sys
import threading
import webbrowser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from cache import get_all_roles, get_last_loaded, load_cache
from config import get_settings
from routers import comparison as comparison_router
from routers import modules as modules_router
from routers import roles as roles_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


try:
    settings = get_settings()
except ValidationError as e:
    raise RuntimeError(
        f"Missing required environment variables - check .env file. Details: {e}"
    ) from e


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("SAP Role Visualizer  up - loading role cache...")
    await asyncio.to_thread(load_cache)
    logger.info("Startup complete. API is ready.")

    yield

    logger.info("SAP Role Visualizer API shutting down.")


app = FastAPI(
    title="SAP Role Access Visualizer API",
    version="1.0.0",
    description="Read-only REST API for browsing SAP S/4HANA composite roles.",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------------------------------------------------------
# API routers
# ---------------------------------------------------------

app.include_router(roles_router.router)
app.include_router(modules_router.router)
app.include_router(comparison_router.router)


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, Any]:
    last = get_last_loaded()

    return {
        "status": "ok",
        "cached_roles": len(get_all_roles()),
        "last_loaded": last.isoformat() if last else None,
    }


@app.post("/api/refresh", tags=["Data"])
async def refresh_data() -> dict[str, Any]:
    logger.info("Manual cache refresh triggered.")

    await asyncio.to_thread(load_cache)

    last = get_last_loaded()

    return {
        "status": "ok",
        "cached_roles": len(get_all_roles()),
        "last_loaded": last.isoformat() if last else None,
    }


# ---------------------------------------------------------
# Frontend
# ---------------------------------------------------------

if getattr(sys, "frozen", False):
    # Running as PyInstaller executable
    frontend_dir = Path(sys._MEIPASS) / "frontend" / "dist"
else:
    # Running normally from source
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"


if frontend_dir.exists():
    logger.info("Serving frontend from: %s", frontend_dir)

    app.mount(
        "/",
        StaticFiles(
            directory=str(frontend_dir),
            html=True,
        ),
        name="frontend",
    )
else:
    logger.warning(
        "Frontend build not found at: %s",
        frontend_dir,
    )


# ---------------------------------------------------------
# Executable entry point
# ---------------------------------------------------------

if __name__ == "__main__":

    threading.Timer(
        1.5,
        lambda: webbrowser.open("http://127.0.0.1:8000"),
    ).start()

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )