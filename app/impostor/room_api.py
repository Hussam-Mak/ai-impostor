"""HTTP routes for group chat rooms."""

from __future__ import annotations

from typing import Callable, Literal

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from .rooms import ALIASES, RoomManager

PlayerId = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
Alias = Literal[ALIASES]  # type: ignore[valid-type]


class RoomPlayerRequest(BaseModel):
    player_id: str = PlayerId


class RoomMessageRequest(BaseModel):
    player_id: str = PlayerId
    text: str = Field(min_length=1, max_length=500)


class RoomVoteRequest(BaseModel):
    player_id: str = PlayerId
    votes: dict[Alias, Literal["ai", "human"]] = Field(min_length=1, max_length=len(ALIASES))


def add_room_routes(app: FastAPI, rooms: RoomManager, limit_join: Callable[[Request], None]) -> None:
    @app.post("/api/rooms/join")
    def join_room(body: RoomPlayerRequest, request: Request) -> dict:
        limit_join(request)
        return rooms.join(body.player_id)

    @app.post("/api/rooms/poll")
    def poll_room(body: RoomPlayerRequest) -> dict:
        return rooms.poll(body.player_id)

    @app.post("/api/rooms/cancel")
    def cancel_room(body: RoomPlayerRequest) -> dict:
        rooms.cancel(body.player_id)
        return {"status": "idle"}

    @app.post("/api/rooms/{room_id}/state")
    def room_state(room_id: str, body: RoomPlayerRequest, since: int = 0) -> dict:
        return rooms.view(body.player_id, room_id, since)

    @app.post("/api/rooms/{room_id}/messages")
    def room_message(room_id: str, body: RoomMessageRequest) -> dict:
        rooms.send_message(body.player_id, room_id, body.text)
        return {"ok": True}

    @app.post("/api/rooms/{room_id}/vote")
    def room_vote(room_id: str, body: RoomVoteRequest) -> dict:
        return rooms.vote(body.player_id, room_id, dict(body.votes))
