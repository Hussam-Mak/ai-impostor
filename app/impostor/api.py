"""HTTP API and app wiring for AI Impostor."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai_player import AIResponder, ChatModel, DatabricksChatModel, MockChatModel
from .config import Settings, load_settings
from .game import GameError, GameManager
from .ratelimit import RateLimiter
from .storage import DeltaRecorder, GameRecorder, JsonlRecorder

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
LLM_HTTP_TIMEOUT_SECONDS = 25
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

PlayerId = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")


class JoinRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=20, pattern=r"^[\w .\-']+$")


class PlayerRequest(BaseModel):
    player_id: str = PlayerId


class MessageRequest(BaseModel):
    player_id: str = PlayerId
    text: str = Field(min_length=1, max_length=500)


class GuessRequest(BaseModel):
    player_id: str = PlayerId
    guess: Literal["ai", "human"]


def running_on_databricks_apps() -> bool:
    return bool(os.getenv("DATABRICKS_APP_PORT"))


def _workspace_client():  # -> WorkspaceClient | None
    if os.getenv("IMPOSTOR_OFFLINE", "").lower() in {"1", "true", "yes"}:
        return None
    try:
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient(http_timeout_seconds=LLM_HTTP_TIMEOUT_SECONDS)
    except Exception as exc:  # no host/credentials configured
        level = logging.ERROR if running_on_databricks_apps() else logging.WARNING
        log.log(level, "No Databricks workspace credentials (%s). Using the offline mock AI.", exc)
        return None


def build_services(settings: Settings) -> tuple[GameManager, dict]:
    client = _workspace_client()
    model: ChatModel = DatabricksChatModel(client, settings.llm_endpoint) if client else MockChatModel()
    recorder: GameRecorder
    if client and settings.warehouse_id:
        recorder = DeltaRecorder(client, settings.warehouse_id, settings.catalog, settings.schema, settings.llm_endpoint)
        log.info("Logging games to Delta in %s.%s", settings.catalog, settings.schema)
    else:
        if running_on_databricks_apps():
            log.error("DATABRICKS_WAREHOUSE_ID is not set; games go to local JSONL and are lost on restart.")
        recorder = JsonlRecorder(settings.local_data_dir, settings.llm_endpoint)
    budget = RateLimiter(limit=settings.llm_calls_per_hour, window_seconds=3600) if client else None
    responder = AIResponder(model, budget=budget)
    manager = GameManager(settings, on_ai_turn=responder.on_ai_turn, on_game_finished=recorder.record)
    responder.bind(manager)
    log.info("AI Impostor ready (AI: %s)", settings.llm_endpoint if client else "mock")
    return manager, {"mode": "databricks" if client else "offline"}


def client_key(request: Request, *, on_databricks: bool | None = None, proxy_hops: int = 1) -> str:
    """Who is calling, for rate limits.

    Only the Databricks Apps proxy sets X-Forwarded-Email, so it is trusted only there.
    Elsewhere the client IP is the X-Forwarded-For entry our own proxy appended
    (counted from the right); entries further left are set by the client.
    """
    trust_email = running_on_databricks_apps() if on_databricks is None else on_databricks
    email = request.headers.get("x-forwarded-email")
    if trust_email and email:
        return f"user:{email.lower()}"
    hops = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if hops and proxy_hops > 0:
        ip = hops[-min(proxy_hops, len(hops))]
    else:
        ip = request.client.host if request.client else "unknown"
    return f"ip:{ip}"


def create_app(
    manager: GameManager | None = None,
    info: dict | None = None,
    join_limiter: RateLimiter | None = None,
    match_limiter: RateLimiter | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    if manager is None:
        settings = settings or load_settings()
        manager, info = build_services(settings)
    runtime_info = info or {}
    origins = list(settings.allowed_origins) if settings else []
    proxy_hops = settings.proxy_hops if settings else 1
    joins = join_limiter or RateLimiter(limit=10, window_seconds=60)
    matches = match_limiter or RateLimiter(limit=30, window_seconds=60)
    app = FastAPI(title="AI Impostor", docs_url=None, redoc_url=None, openapi_url=None)
    if origins:
        # Lets the GitHub Pages front end call this server. No cookies are involved.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
            allow_credentials=False,
            max_age=600,
        )

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.exception_handler(GameError)
    async def _game_error(_request: Request, exc: GameError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    def limit(limiter: RateLimiter, request: Request) -> None:
        if not limiter.allow(client_key(request, proxy_hops=proxy_hops)):
            raise HTTPException(429, "Too many requests. Take a breather and try again.")

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, **runtime_info}

    @app.post("/api/players")
    def join(body: JoinRequest, request: Request) -> dict:
        limit(joins, request)
        nickname = " ".join(body.nickname.split())
        if not nickname:
            raise HTTPException(422, "Nickname is empty.")
        return {"player_id": manager.register_player(nickname), "nickname": nickname}

    @app.post("/api/match")
    def request_match(body: PlayerRequest, request: Request) -> dict:
        limit(matches, request)
        return manager.request_match(body.player_id)

    @app.post("/api/match/poll")
    def poll_match(body: PlayerRequest) -> dict:
        return manager.poll_match(body.player_id)

    @app.post("/api/match/cancel")
    def cancel_match(body: PlayerRequest) -> dict:
        manager.cancel_match(body.player_id)
        return {"status": "idle"}

    @app.post("/api/games/{game_id}/state")
    def game_state(game_id: str, body: PlayerRequest, since: int = 0) -> dict:
        return manager.view_game(body.player_id, game_id, since)

    @app.post("/api/games/{game_id}/messages")
    def send_message(game_id: str, body: MessageRequest) -> dict:
        manager.send_message(body.player_id, game_id, body.text)
        return {"ok": True}

    @app.post("/api/games/{game_id}/guess")
    def guess(game_id: str, body: GuessRequest) -> dict:
        return manager.submit_guess(body.player_id, game_id, body.guess)

    @app.get("/api/leaderboard")
    def leaderboard() -> list[dict]:
        return manager.leaderboard()

    @app.get("/api/stats")
    def stats() -> dict:
        return manager.stats()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
