from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import chat, graphs, health
from app.core.config import get_settings
from app.graphs.store import build_store
from app.services.runner import build_runner, build_session_service


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
