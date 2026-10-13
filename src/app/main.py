import logging
import re
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.routes import chat, graphs, health
from app.core.config import get_settings
from app.core.logs import configure_logging, log, request_id
from app.graphs.store import build_store
from app.services.runner import build_runner, build_session_service

configure_logging()
logger = logging.getLogger("app.requests")

# A caller may send its own X-Request-ID (to follow one request across
# services); anything else gets a fresh id.
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the agents and the session store once, when the server starts.
    settings = get_settings()
    app.state.runner = build_runner(build_session_service(settings))
    app.state.graph_store = build_store(settings)  # Graph Creator proposals
    yield
    await app.state.runner.close()


app = FastAPI(title="Vehicle Safety Assistant", version="0.1.0", lifespan=lifespan)
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(graphs.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Give every request an id and log one line when it finishes."""
    incoming = request.headers.get("X-Request-ID", "")
    rid = incoming if SAFE_REQUEST_ID.match(incoming) else uuid4().hex[:12]
    token = request_id.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log(logger, logging.ERROR, "request failed", method=request.method, path=request.url.path,
            status=500, latency_ms=round((time.perf_counter() - start) * 1000))
        raise
    else:
        # Health checks run constantly; keep them out of the INFO logs.
        level = logging.DEBUG if request.url.path in ("/", "/health") else logging.INFO
        log(logger, level, "request", method=request.method, path=request.url.path,
            status=response.status_code, latency_ms=round((time.perf_counter() - start) * 1000))
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        request_id.reset(token)
