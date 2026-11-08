"""Persist finished games.

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


class GameRecorder(Protocol):
    def record(self, game: GameRecord) -> None: ...


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


_SQL_TYPES = {"started_at": "TIMESTAMP", "chat_closed_at": "TIMESTAMP", "finished_at": "TIMESTAMP",
              "sent_at": "TIMESTAMP", "guessed_at": "TIMESTAMP", "seq": "INT", "player_count": "INT",
              "message_count": "INT", "points": "INT", "correct": "BOOLEAN"}


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
        if not self._slots.acquire(blocking=False):
            log.error("Delta write queue full; dropping game %s", game.game_id)
            return
        self._executor.submit(self._write, game)

    def _write(self, game: GameRecord) -> None:
        try:
            rows_by_table = record_rows(game, self._llm_endpoint)
            for table in TABLE_WRITE_ORDER:
                rows = rows_by_table[table]
                for start in range(0, len(rows), ROWS_PER_INSERT):
                    sql, params = build_insert(f"{self._prefix}.`{table}`", rows[start : start + ROWS_PER_INSERT])
                    self._execute(sql, params)
        except Exception:
            log.exception("Failed to write game %s to Delta", game.game_id)
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
        try:
            line = json.dumps({"record": asdict(game), "rows": record_rows(game, self._llm_endpoint)})
            with self._lock, open(self._path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except (OSError, TypeError, ValueError):
            log.exception("Failed to write game %s to %s", game.game_id, self._path)
