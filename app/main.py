from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routers import agent, demo, distributors, invoices, merchants, metrics, payments, webhooks
from app.config import settings
from app.bootstrap import ensure_seeded
from app.ai.graph.tracing import configure_langsmith
import asyncio

from sqlmodel import Session

from app import clock
from app.container import Container, build_container
from app.jobs.scheduler import run_forever, tick
from app.db import engine
from app.services.errors import ServiceError


def create_app(container: Container | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_langsmith(settings)
        if getattr(app.state, "container", None) is None:
            app.state.container = build_container(settings)
        if settings.auto_seed:
            ensure_seeded(engine)
        stop, task = asyncio.Event(), None
        if settings.scheduler_enabled:
            task = asyncio.create_task(run_forever(
                lambda: tick(lambda: Session(engine), app.state.container, clock.now(), settings.scheduler_hour),
                settings.scheduler_interval_s, stop))
        yield
        if task is not None:
            stop.set()
            await task

    app = FastAPI(title="Hisaab Agent", lifespan=lifespan)
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    app.state.container = container

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError):
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=exc.status)

    @app.get("/health")
    def health():
        return {"ok": True}

    for r in (invoices.router, merchants.router, payments.router, agent.router, distributors.router, demo.router, metrics.router, webhooks.router):
        app.include_router(r)
    # Only voice replies and reports are public; bill images stay private on disk.
    media_root = container.media.root if container else Path(settings.media_dir)  # same dir the container writes to
    for kind in ("audio", "reports"):
        (media_root / kind).mkdir(parents=True, exist_ok=True)
        app.mount(f"/media/{kind}", StaticFiles(directory=media_root / kind), name=kind)
    return app


app = create_app()
