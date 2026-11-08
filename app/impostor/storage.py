"""Persist finished games and group rooms.

On Databricks: parameterized INSERTs into Unity Catalog Delta tables through a
SQL warehouse (Statement Execution API). Locally: one JSON line per game.
Writes happen on a single background thread (bounded queue) so gameplay never waits on them.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Protocol

from .game import AI_SENDER, GameRecord
from .rooms import RoomRecord

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementParameterListItem

log = logging.getLogger(__name__)

ROWS_PER_INSERT = 40
MAX_PENDING_WRITES = 500
STATEMENT_POLL_SECONDS = 5.0
STATEMENT_MAX_WAIT_SECONDS = 300.0
# Write games last: a games row then means its messages and guesses are in.
TABLE_WRITE_ORDER = ("messages", "guesses", "games")
ROOM_TABLE_WRITE_ORDER = ("room_messages", "room_seats", "room_votes", "rooms")


class GameRecorder(Protocol):
    def record(self, game: GameRecord) -> None: ...

    def record_room(self, room: RoomRecord) -> None: ...


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def record_rows(game: GameRecord, llm_endpoint: str) -> dict[str, list[dict]]:
    """Flatten a finished game into rows for the three tables."""
    nicknames = dict(game.players)
    persona = game.persona_key if game.opponent_type == "ai" else None
    games = [
        {
            "game_id": game.game_id,
            "opponent_type": game.opponent_type,
            "persona": persona,
            "llm_endpoint": llm_endpoint if game.opponent_type == "ai" else None,
            "started_at": iso(game.started_at),
            "chat_closed_at": iso(game.chat_closed_at),
            "finished_at": iso(game.finished_at),
            "closed_reason": game.closed_reason,
            "player_count": len(game.players),
            "message_count": len(game.messages),
        }
    ]
    messages = [
        {
            "game_id": game.game_id,
            "seq": m.seq,
            "sender_kind": "ai" if m.sender == AI_SENDER else "human",
            "sender_nickname": None if m.sender == AI_SENDER else nicknames.get(m.sender),
            "text": m.text,
            "sent_at": iso(m.sent_at),
        }
        for m in game.messages
    ]
    guesses = [
        {
            "game_id": game.game_id,
            "opponent_type": game.opponent_type,
            "persona": persona,
            "player_nickname": nicknames.get(pid),
            "guess": g.guess,
            "correct": g.correct,
            "points": g.points,
            "guessed_at": iso(g.guessed_at),
        }
        for pid, g in game.guesses
    ]
    return {"games": games, "messages": messages, "guesses": guesses}


def room_rows(room: RoomRecord, llm_endpoint: str) -> dict[str, list[dict]]:
    """Flatten a finished group room into rows for the four room tables."""
    seats = {s.alias: s for s in room.seats}
    judged: dict[str, list[str]] = {}
    for _voter, alias, vote in room.votes:
        judged.setdefault(alias, []).append(vote)
    rooms = [{
        "room_id": room.room_id,
        "llm_endpoint": llm_endpoint,
        "started_at": iso(room.started_at),
        "chat_closed_at": iso(room.chat_closed_at),
        "finished_at": iso(room.finished_at),
        "human_count": sum(1 for s in room.seats if s.kind == "human"),
        "ai_count": sum(1 for s in room.seats if s.kind == "ai"),
        "message_count": len(room.messages),
    }]
    room_seats = [{
        "room_id": room.room_id,
        "alias": s.alias,
        "sender_kind": s.kind,
        "persona": s.persona_key,
        "player_nickname": s.nickname,
        "voted_ai": sum(1 for v in judged.get(s.alias, []) if v == "ai"),
        "votes": len(judged.get(s.alias, [])),
    } for s in room.seats]
    room_messages = [{
        "room_id": room.room_id,
        "seq": m.seq,
        "alias": m.alias,
        "sender_kind": seats[m.alias].kind if m.alias in seats else None,
        "persona": seats[m.alias].persona_key if m.alias in seats else None,
        "sender_nickname": seats[m.alias].nickname if m.alias in seats else None,
        "text": m.text,
        "sent_at": iso(m.sent_at),
    } for m in room.messages]
    room_votes = [{
        "room_id": room.room_id,
        "voter_nickname": voter,
        "target_alias": alias,
        "target_kind": seats[alias].kind if alias in seats else None,
        "target_persona": seats[alias].persona_key if alias in seats else None,
        "vote": vote,
        "correct": (alias in seats and seats[alias].kind == vote),
    } for voter, alias, vote in room.votes]
    return {"rooms": rooms, "room_seats": room_seats, "room_messages": room_messages, "room_votes": room_votes}


_SQL_TYPES = {"started_at": "TIMESTAMP", "chat_closed_at": "TIMESTAMP", "finished_at": "TIMESTAMP",
              "sent_at": "TIMESTAMP", "guessed_at": "TIMESTAMP", "seq": "INT", "player_count": "INT",
              "message_count": "INT", "points": "INT", "correct": "BOOLEAN", "human_count": "INT",
              "ai_count": "INT", "voted_ai": "INT", "votes": "INT"}


def build_insert(table: str, rows: list[dict]) -> tuple[str, list[tuple[str, str | None, str]]]:
    """Build one multi-row parameterized INSERT. Values never touch the SQL text."""
    columns = list(rows[0].keys())
    params: list[tuple[str, str | None, str]] = []
    value_groups = []
    for i, row in enumerate(rows):
        names = []
        for col in columns:
            name = f"{col}_{i}"
            value = row[col]
            sql_type = _SQL_TYPES.get(col, "STRING")
            text = None if value is None else (str(value).lower() if isinstance(value, bool) else str(value))
            params.append((name, text, sql_type))
            names.append(f"CAST(:{name} AS {sql_type})")
        value_groups.append(f"({', '.join(names)})")
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES {', '.join(value_groups)}"
    return sql, params


class DeltaRecorder:
    """Writes finished games to Unity Catalog Delta tables via a SQL warehouse.

    Tables are created by the setup job (notebooks/00_setup_tables.py), so the
    app's service principal only needs MODIFY on them.
    """

    def __init__(
        self,
        client: WorkspaceClient,
        warehouse_id: str,
        catalog: str,
        schema: str,
        llm_endpoint: str,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._warehouse_id = warehouse_id
        self._prefix = f"`{catalog}`.`{schema}`"  # identifiers validated in config.load_settings
        self._llm_endpoint = llm_endpoint
        self._sleep = sleep
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="delta-writer")
        self._slots = threading.BoundedSemaphore(MAX_PENDING_WRITES)

    def record(self, game: GameRecord) -> None:
        self._enqueue(f"game {game.game_id}", lambda: record_rows(game, self._llm_endpoint), TABLE_WRITE_ORDER)

    def record_room(self, room: RoomRecord) -> None:
        self._enqueue(f"room {room.room_id}", lambda: room_rows(room, self._llm_endpoint), ROOM_TABLE_WRITE_ORDER)

    def _enqueue(self, label: str, build: Callable[[], dict[str, list[dict]]], order: tuple[str, ...]) -> None:
        if not self._slots.acquire(blocking=False):
            log.error("Delta write queue full; dropping %s", label)
            return
        self._executor.submit(self._write, label, build, order)

    def _write(self, label: str, build: Callable[[], dict[str, list[dict]]], order: tuple[str, ...]) -> None:
        try:
            rows_by_table = build()
            for table in order:
                rows = rows_by_table[table]
                for start in range(0, len(rows), ROWS_PER_INSERT):
                    sql, params = build_insert(f"{self._prefix}.`{table}`", rows[start : start + ROWS_PER_INSERT])
                    self._execute(sql, params)
        except Exception:
            log.exception("Failed to write %s to Delta", label)
        finally:
            self._slots.release()

    def _execute(self, sql: str, params: list[tuple[str, str | None, str]]) -> None:
        from databricks.sdk.service.sql import StatementParameterListItem, StatementState

        items: list[StatementParameterListItem] = [
            StatementParameterListItem(name=n, value=v, type=t) for n, v, t in params
        ]
        response = self._client.statement_execution.execute_statement(
            statement=sql, warehouse_id=self._warehouse_id, parameters=items or None, wait_timeout="50s"
        )
        waited = 0.0
        # A cold warehouse can take minutes to start; keep polling instead of giving up.
        while (
            response.status
            and response.status.state in (StatementState.PENDING, StatementState.RUNNING)
            and waited < STATEMENT_MAX_WAIT_SECONDS
        ):
            self._sleep(STATEMENT_POLL_SECONDS)
            waited += STATEMENT_POLL_SECONDS
            response = self._client.statement_execution.get_statement(response.statement_id)
        state = response.status.state if response.status else None
        if state != StatementState.SUCCEEDED:
            error = response.status.error.message if response.status and response.status.error else state
            raise RuntimeError(f"Statement did not succeed: {error}")


class JsonlRecorder:
    """Local fallback: appends each finished game as one JSON line."""

    def __init__(self, directory: str, llm_endpoint: str) -> None:
        os.makedirs(directory, exist_ok=True)
        self._path = os.path.join(directory, "games.jsonl")
        self._llm_endpoint = llm_endpoint
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return self._path

    def record(self, game: GameRecord) -> None:
        self._append({"record": asdict(game), "rows": record_rows(game, self._llm_endpoint)}, f"game {game.game_id}")

    def record_room(self, room: RoomRecord) -> None:
        self._append({"room": room.room_id, "rows": room_rows(room, self._llm_endpoint)}, f"room {room.room_id}")

    def _append(self, payload: dict, label: str) -> None:
        try:
            line = json.dumps(payload)
            with self._lock, open(self._path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except (OSError, TypeError, ValueError):
            log.exception("Failed to write %s to %s", label, self._path)
