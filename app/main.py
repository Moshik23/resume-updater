from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth import BasicAuthMiddleware
from app.routes import health, jobs, profiles

app = FastAPI(title="Resume Updater")

app.add_middleware(BasicAuthMiddleware)

app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(profiles.router)

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
