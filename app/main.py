"""FastAPI application: one service, HTTP + WebSockets.

Routes:
  GET  /health         liveness
  GET  /api/token      Twilio Voice Access Token for the browser Device
  POST /twiml/voice    TwiML: fork both tracks + dial the customer
  POST /twiml/status   dialed-leg status callback (drives status + teardown)
  WS   /ws/{callId}    browser push: status / transcript / coach / summary
  WS   /media/{callId} Twilio Media Streams (both tracks) -> Deepgram
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import token as token_routes
from app.routes import twiml as twiml_routes
from app.ws import browser as browser_ws
from app.ws import media as media_ws
from app import db, calls
from app.agents.router import router as agents_router
from app.rag.router import router as knowledge_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.initialize()
    log.info("AI Sales Coach starting — public host: %s", settings.public_host() or "(unset)")
    yield
    log.info("AI Sales Coach shutting down")


def create_app() -> FastAPI:
    app = FastAPI(title="AI Sales Coach", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(token_routes.router)
    app.include_router(twiml_routes.router)
    app.include_router(browser_ws.router)
    app.include_router(media_ws.router)
    app.include_router(agents_router)
    app.include_router(knowledge_router)
    app.include_router(calls.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
