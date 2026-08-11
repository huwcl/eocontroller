"""
main.py

FastAPI entry point. Starts the background poller on startup (which is
what actually keeps a charge session alive continuously - see
core/poller.py) and exposes the REST API on top of it.

Run with: uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.poller import run_poll_loop
from api.routes import router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    poll_task = asyncio.create_task(run_poll_loop())
    yield
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="eocontroller", lifespan=lifespan)
app.include_router(router)
