"""In-memory game engine: players, matchmaking, chat rounds, guesses, scoring.

All state lives behind one lock. Callbacks (AI turns, finished-game recording)
are collected while the lock is held and fired after it is released, in a
`finally`, so a slow or failing callback never blocks or loses game state.

Fairness: nothing a player can observe before guessing should reveal the
opponent type. Human and AI matches both take 3-9s to appear, and both kinds of
opponent can end a chat early (humans by guessing, the AI by "leaving").
"""

from __future__ import annotations

import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal

from .config import Settings
from .personas import Persona, persona_by_key, pick_persona

log = logging.getLogger(__name__)

Guess = Literal["ai", "human"]
OpponentType = Literal["ai", "human"]
AI_SENDER = "ai"

GUESS_GRACE_SECONDS = 60.0  # how long after chat closes we wait for guesses
QUEUE_STALE_SECONDS = 15.0  # drop queued players who stopped polling
FINISHED_GAME_TTL_SECONDS = 600.0
PLAYER_TTL_SECONDS = 7200.0
AI_OPENS_PROBABILITY = 0.5
AI_LEAVES_EARLY_PROBABILITY = 0.25
AI_LEAVE_WINDOW = (0.45, 0.9)  # fraction of the round when the AI may leave
MAX_PLAYERS = 5000
MAX_ACTIVE_GAMES = 1000
MAX_MESSAGES_PER_GAME = 120
MAX_AI_MESSAGES_PER_GAME = 40
BASE_POINTS = 100
STREAK_BONUS = 25
MAX_STREAK_BONUS_STEPS = 4


class GameError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Message:
    seq: int
    sender: str  # player id, or AI_SENDER
    text: str
    sent_at: float


@dataclass(frozen=True)
class GuessResult:
    guess: Guess
    correct: bool
    points: int
    guessed_at: float


@dataclass
class Player:
    id: str
    nickname: str
    last_seen: float
    score: int = 0
    streak: int = 0
    best_streak: int = 0
    games_played: int = 0
    correct: int = 0
    game_id: str | None = None
    queued_until: float | None = None  # when the AI fallback kicks in
    match_visible_at: float = 0.0  # a found match is shown only from this time


@dataclass
class Game:
    id: str
    opponent_type: OpponentType
    player_ids: tuple[str, ...]
    started_at: float
    ends_at: float
    persona_key: str | None
    ai_leave_at: float | None = None
    messages: list[Message] = field(default_factory=list)
    guesses: dict[str, GuessResult] = field(default_factory=dict)
    last_seen: dict[str, float] = field(default_factory=dict)
    last_message_at: dict[str, float] = field(default_factory=dict)
    chat_closed_at: float | None = None
    closed_reason: str | None = None  # timer | early_guess | partner_left | ai_left
    closed_by: str | None = None
    finished_at: float | None = None
    ai_pending: bool = False


@dataclass(frozen=True)
class AITurn:
    """Snapshot handed to the AI responder."""

    game_id: str
    persona: Persona
    history: tuple[tuple[bool, str], ...]  # (is_ai, text)
    last_seq: int
    seconds_left: float


@dataclass(frozen=True)
class GameRecord:
    """Everything persisted about a finished game."""

    game_id: str
    opponent_type: OpponentType
    persona_key: str | None
    started_at: float
    chat_closed_at: float
    finished_at: float
    closed_reason: str
    players: tuple[tuple[str, str], ...]  # (player_id, nickname)
    messages: tuple[Message, ...]
    guesses: tuple[tuple[str, GuessResult], ...]


Action = Callable[[], None]


class GameManager:
    def __init__(
        self,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.time,
        rng: random.Random | None = None,
        on_ai_turn: Callable[[str], None] | None = None,
        on_game_finished: Callable[[GameRecord], None] | None = None,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._rng = rng or random.Random()
        self._on_ai_turn = on_ai_turn or (lambda _gid: None)
        self._on_game_finished = on_game_finished or (lambda _rec: None)
        self._lock = threading.RLock()
        self._players: dict[str, Player] = {}
        self._games: dict[str, Game] = {}
        self._queue: list[str] = []
        self._totals = {"games": 0, "ai_total": 0, "ai_correct": 0, "human_total": 0, "human_correct": 0}

    # ------------------------------------------------------------------ players
    def register_player(self, nickname: str) -> str:
        player_id = uuid.uuid4().hex
        with self._lock:
            if len(self._players) >= MAX_PLAYERS:
                raise GameError("The game is full right now. Try again in a minute.", 503)
            self._players[player_id] = Player(player_id, nickname, self._clock())
        return player_id

    def _player(self, player_id: str) -> Player:
        player = self._players.get(player_id)
        if player is None:
            raise GameError("Unknown player. Please rejoin.", 404)
        player.last_seen = self._clock()
        return player

    # -------------------------------------------------------------- matchmaking
    def request_match(self, player_id: str) -> dict:
        actions: list[Action] = []
        try:
            with self._lock:
                self._cleanup(actions)
                player = self._player(player_id)
                self._release_finished_game(player)
                if player.game_id is None and player.queued_until is None:
                    self._enqueue_or_pair(actions, player)
                return self._match_status(actions, player)
        finally:
            self._run(actions)

    def poll_match(self, player_id: str) -> dict:
        actions: list[Action] = []
        try:
            with self._lock:
                return self._match_status(actions, self._player(player_id))
        finally:
            self._run(actions)

    def cancel_match(self, player_id: str) -> None:
        with self._lock:
            player = self._player(player_id)
            if player.game_id is None:
                self._dequeue(player)

    def _enqueue_or_pair(self, actions: list[Action], player: Player) -> None:
        active = sum(1 for g in self._games.values() if g.finished_at is None)
        if active >= MAX_ACTIVE_GAMES:
            raise GameError("All tables are busy. Try again in a minute.", 503)
        partner = self._pick_waiting_human(player.id)
        if partner is not None:
            # Reveal the match when the partner's own wait ends, so a human match
            # takes as long to appear as an AI match would have.
            start = partner.queued_until or self._clock()
            self._dequeue(partner)
            self._start_game(actions, "human", (partner.id, player.id), start)
            return
        wait = self._rng.uniform(self._settings.match_wait_min, self._settings.match_wait_max)
        player.queued_until = self._clock() + wait
        self._queue.append(player.id)

    def _pick_waiting_human(self, player_id: str) -> Player | None:
        now = self._clock()
        alive = [
            self._players[pid]
            for pid in self._queue
            if pid != player_id
            and pid in self._players
            and now - self._players[pid].last_seen < QUEUE_STALE_SECONDS
            # Only pair if the newcomer would still wait at least the minimum.
            and (self._players[pid].queued_until or 0) - now >= self._settings.match_wait_min
        ]
        if not alive or self._rng.random() >= self._settings.human_match_probability:
            return None
        return alive[0]

    def _dequeue(self, player: Player) -> None:
        player.queued_until = None
        self._queue = [pid for pid in self._queue if pid != player.id]

    def _match_status(self, actions: list[Action], player: Player) -> dict:
        now = self._clock()
        if player.game_id is not None:
            if now < player.match_visible_at:
                return {"status": "waiting", "game_id": None}
            return {"status": "matched", "game_id": player.game_id}
        if player.queued_until is None:
            return {"status": "idle", "game_id": None}
        if now >= player.queued_until:
            self._dequeue(player)
            game = self._start_game(actions, "ai", (player.id,), now)
            return {"status": "matched", "game_id": game.id}
        return {"status": "waiting", "game_id": None}

    def _start_game(
        self, actions: list[Action], opponent: OpponentType, player_ids: tuple[str, ...], start: float
    ) -> Game:
        persona = pick_persona(self._rng) if opponent == "ai" else None
        round_seconds = self._settings.round_seconds
        leave_at = None
        if opponent == "ai" and self._rng.random() < AI_LEAVES_EARLY_PROBABILITY:
            leave_at = start + round_seconds * self._rng.uniform(*AI_LEAVE_WINDOW)
        game = Game(
            id=uuid.uuid4().hex,
            opponent_type=opponent,
            player_ids=player_ids,
            started_at=start,
            ends_at=start + round_seconds,
            persona_key=persona.key if persona else None,
            ai_leave_at=leave_at,
            last_seen={pid: start for pid in player_ids},
        )
        self._games[game.id] = game
        for pid in player_ids:
            p = self._players[pid]
            self._dequeue(p)
            p.game_id = game.id
            p.match_visible_at = start
        if opponent == "ai" and self._rng.random() < AI_OPENS_PROBABILITY:
            game.ai_pending = True
            actions.append(lambda gid=game.id: self._start_ai_turn(gid))
        return game

    def _release_finished_game(self, player: Player) -> None:
        if player.game_id is None:
            return
        game = self._games.get(player.game_id)
        if game is None or player.id in game.guesses or game.finished_at is not None:
            player.game_id = None

    # --------------------------------------------------------------------- chat
    def send_message(self, player_id: str, game_id: str, text: str) -> None:
        actions: list[Action] = []
        try:
            with self._lock:
                player = self._player(player_id)
                game = self._game_for(player, game_id)
                now = self._clock()
                game.last_seen[player.id] = max(game.last_seen.get(player.id, now), now)
                self._advance(actions, game)
                self._check_can_send(game, player, text)
                clean = text.strip()[: self._settings.max_message_chars]
                game.last_message_at[player.id] = now
                game.messages.append(Message(len(game.messages) + 1, player.id, clean, now))
                if game.opponent_type == "ai" and not game.ai_pending:
                    game.ai_pending = True
                    actions.append(lambda gid=game.id: self._start_ai_turn(gid))
        finally:
            self._run(actions)

    def _check_can_send(self, game: Game, player: Player, text: str) -> None:
        now = self._clock()
        if now < game.started_at:
            raise GameError("The chat hasn't started yet.", 409)
        if game.chat_closed_at is not None:
            raise GameError("Chat is over. Time to guess!", 409)
        if not text.strip():
            raise GameError("Message is empty.")
        if len(game.messages) >= MAX_MESSAGES_PER_GAME:
            raise GameError("That's enough messages for one round.", 429)
        last = game.last_message_at.get(player.id)
        if last is not None and now - last < self._settings.min_seconds_between_messages:
            raise GameError("Slow down a little.", 429)

    def _start_ai_turn(self, game_id: str) -> None:
        try:
            self._on_ai_turn(game_id)
        except Exception:
            log.exception("Could not schedule AI turn for game %s", game_id)
            self.release_ai_turn(game_id)

    def claim_ai_turn(self, game_id: str) -> AITurn | None:
        """Snapshot of the chat for the AI to reply to, or None if the AI should stay quiet."""
        actions: list[Action] = []
        try:
            with self._lock:
                game = self._games.get(game_id)
                if game is None:
                    return None
                self._advance(actions, game)
                persona = persona_by_key(game.persona_key or "")
                ai_sent = sum(1 for m in game.messages if m.sender == AI_SENDER)
                if game.chat_closed_at is not None or persona is None or ai_sent >= MAX_AI_MESSAGES_PER_GAME:
                    game.ai_pending = False
                    return None
                history = tuple((m.sender == AI_SENDER, m.text) for m in game.messages)
                seconds_left = max(0.0, game.ends_at - self._clock())
                return AITurn(game.id, persona, history, len(game.messages), seconds_left)
        finally:
            self._run(actions)

    def post_ai_message(self, game_id: str, text: str | None, snapshot_seq: int) -> bool:
        """Post the AI reply. Returns True if the human wrote more since the snapshot."""
        actions: list[Action] = []
        try:
            with self._lock:
                game = self._games.get(game_id)
                if game is None:
                    return False
                self._advance(actions, game)
                if game.chat_closed_at is not None:
                    game.ai_pending = False
                    return False
                newer_human = any(m.sender != AI_SENDER for m in game.messages[snapshot_seq:])
                # An opening "hey" is stale once the human has already spoken; reply to them instead.
                stale_opener = snapshot_seq == 0 and newer_human
                if text and not stale_opener:
                    game.messages.append(Message(len(game.messages) + 1, AI_SENDER, text, self._clock()))
                game.ai_pending = newer_human
                return newer_human
        finally:
            self._run(actions)

    def release_ai_turn(self, game_id: str) -> None:
        """Clear the pending flag after a failed AI turn so the next message retries."""
        with self._lock:
            game = self._games.get(game_id)
            if game is not None:
                game.ai_pending = False

    # ------------------------------------------------------------------ guesses
    def submit_guess(self, player_id: str, game_id: str, guess: Guess) -> dict:
        actions: list[Action] = []
        try:
            with self._lock:
                player = self._player(player_id)
                game = self._game_for(player, game_id)
                game.last_seen[player.id] = self._clock()
                self._advance(actions, game)
                if player.id in game.guesses:
                    raise GameError("You already guessed.", 409)
                if game.finished_at is not None:
                    raise GameError("This game has ended.", 409)
                if game.chat_closed_at is None:
                    self._close_chat(game, "early_guess", closed_by=player.id)
                correct = guess == game.opponent_type
                points = self._score(player, correct)
                game.guesses[player.id] = GuessResult(guess, correct, points, self._clock())
                self._advance(actions, game)
                return self._view(player, game, since=len(game.messages))
        finally:
            self._run(actions)

    def _score(self, player: Player, correct: bool) -> int:
        player.games_played += 1
        if not correct:
            player.streak = 0
            return 0
        player.correct += 1
        bonus = STREAK_BONUS * min(player.streak, MAX_STREAK_BONUS_STEPS)
        player.streak += 1
        player.best_streak = max(player.best_streak, player.streak)
        points = BASE_POINTS + bonus
        player.score += points
        return points

    # --------------------------------------------------------------------- view
    def view_game(self, player_id: str, game_id: str, since: int = 0) -> dict:
        actions: list[Action] = []
        try:
            with self._lock:
                player = self._player(player_id)
                game = self._game_for(player, game_id)
                game.last_seen[player.id] = self._clock()
                self._advance(actions, game)
                return self._view(player, game, since)
        finally:
            self._run(actions)

    def _view(self, player: Player, game: Game, since: int) -> dict:
        now = self._clock()
        my_guess = game.guesses.get(player.id)
        if game.chat_closed_at is None:
            status = "chatting"
        elif my_guess is None and game.finished_at is None:
            status = "guessing"
        else:
            status = "revealed"
        view: dict = {
            "game_id": game.id,
            "status": status,
            "seconds_left": max(0.0, game.ends_at - now) if status == "chatting" else 0.0,
            "round_seconds": self._settings.round_seconds,
            "closed_reason": self._public_reason(game, player),
            "messages": [
                {"seq": m.seq, "from": "me" if m.sender == player.id else "them", "text": m.text}
                for m in game.messages[max(0, since):]
            ],
            "message_count": len(game.messages),
            "player": self._player_stats(player),
            "reveal": None,
        }
        if status == "revealed":
            view["reveal"] = self._reveal(player, game, my_guess)
        return view

    @staticmethod
    def _public_reason(game: Game, player: Player) -> str | None:
        """How the chat ended, phrased so it never hints at the opponent type."""
        if game.closed_reason is None:
            return None
        if game.closed_reason == "timer":
            return "timer"
        return "you_guessed" if game.closed_by == player.id else "partner_ended"

    def _reveal(self, player: Player, game: Game, my_guess: GuessResult | None) -> dict:
        if game.opponent_type == "ai":
            persona = persona_by_key(game.persona_key or "")
            name = persona.name if persona else "the AI"
            detail = persona.backstory if persona else ""
        else:
            other = next((pid for pid in game.player_ids if pid != player.id), None)
            other_player = self._players.get(other) if other else None
            name = other_player.nickname if other_player else "another player"
            other_guess = game.guesses.get(other) if other else None
            detail = (
                f"They guessed you were {'an AI' if other_guess.guess == 'ai' else 'a human'}."
                if other_guess
                else "They haven't guessed yet."
            )
        return {
            "opponent_type": game.opponent_type,
            "opponent_name": name,
            "persona_key": game.persona_key,
            "detail": detail,
            "your_guess": my_guess.guess if my_guess else None,
            "correct": my_guess.correct if my_guess else None,
            "points": my_guess.points if my_guess else 0,
        }

    @staticmethod
    def _player_stats(player: Player) -> dict:
        return {
            "nickname": player.nickname,
            "score": player.score,
            "streak": player.streak,
            "best_streak": player.best_streak,
            "games_played": player.games_played,
            "correct": player.correct,
        }

    # ---------------------------------------------------------------- lifecycle
    def _game_for(self, player: Player, game_id: str) -> Game:
        game = self._games.get(game_id)
        if game is None or player.id not in game.player_ids:
            raise GameError("Game not found.", 404)
        return game

    def _advance(self, actions: list[Action], game: Game) -> None:
        """Move a game forward based on the clock and who is still around."""
        now = self._clock()
        if game.chat_closed_at is None:
            if now >= game.ends_at:
                self._close_chat(game, "timer")
            elif game.ai_leave_at is not None and now >= game.ai_leave_at:
                self._close_chat(game, "ai_left", closed_by=AI_SENDER)
            elif game.opponent_type == "human":
                limit = self._settings.partner_idle_seconds
                idle = [pid for pid in game.player_ids if now - game.last_seen.get(pid, now) > limit]
                if idle:
                    self._close_chat(game, "partner_left", closed_by=idle[0])
        if game.finished_at is None and game.chat_closed_at is not None:
            all_guessed = all(pid in game.guesses for pid in game.player_ids)
            if all_guessed or now - game.chat_closed_at > GUESS_GRACE_SECONDS:
                self._finish(actions, game)

    def _close_chat(self, game: Game, reason: str, closed_by: str | None = None) -> None:
        game.chat_closed_at = min(self._clock(), game.ends_at)
        game.closed_reason = reason
        game.closed_by = closed_by

    def _finish(self, actions: list[Action], game: Game) -> None:
        game.finished_at = self._clock()
        record = GameRecord(
            game_id=game.id,
            opponent_type=game.opponent_type,
            persona_key=game.persona_key,
            started_at=game.started_at,
            chat_closed_at=game.chat_closed_at or game.finished_at,
            finished_at=game.finished_at,
            closed_reason=game.closed_reason or "unknown",
            players=tuple((pid, self._players[pid].nickname) for pid in game.player_ids if pid in self._players),
            messages=tuple(game.messages),
            guesses=tuple(game.guesses.items()),
        )
        self._totals["games"] += 1
        kind = game.opponent_type
        for result in game.guesses.values():
            self._totals[f"{kind}_total"] += 1
            self._totals[f"{kind}_correct"] += int(result.correct)
        actions.append(lambda: self._on_game_finished(record))

    def _cleanup(self, actions: list[Action]) -> None:
        now = self._clock()
        for game in list(self._games.values()):
            self._advance(actions, game)
            if game.finished_at is not None and now - game.finished_at > FINISHED_GAME_TTL_SECONDS:
                del self._games[game.id]
        for player in list(self._players.values()):
            if now - player.last_seen > PLAYER_TTL_SECONDS:
                self._dequeue(player)
                del self._players[player.id]

    @staticmethod
    def _run(actions: list[Action]) -> None:
        for action in actions:
            try:
                action()
            except Exception:  # one bad callback must not skip the others
                log.exception("Game callback failed")

    # ------------------------------------------------------------------- stats
    def leaderboard(self, limit: int = 10) -> list[dict]:
        with self._lock:
            ranked = sorted(
                (p for p in self._players.values() if p.games_played > 0),
                key=lambda p: (p.score, p.best_streak),
                reverse=True,
            )
            return [self._player_stats(p) for p in ranked[:limit]]

    def stats(self) -> dict:
        with self._lock:
            t = dict(self._totals)

        def rate(correct: int, total: int) -> float | None:
            return round(correct / total, 3) if total else None

        return {
            "games_finished": t["games"],
            "guesses": t["ai_total"] + t["human_total"],
            "overall_accuracy": rate(t["ai_correct"] + t["human_correct"], t["ai_total"] + t["human_total"]),
            "spot_the_ai_accuracy": rate(t["ai_correct"], t["ai_total"]),
            "spot_the_human_accuracy": rate(t["human_correct"], t["human_total"]),
            "ai_fool_rate": rate(t["ai_total"] - t["ai_correct"], t["ai_total"]),
        }
