"""Group chat rooms: a few players plus hidden AI impostors, then everyone votes.

Everyone in a room, human or AI, gets a random alias. After the chat, each
human marks every other seat as human or AI. Like GameManager, all state sits
behind one lock and callbacks run after the lock is released. Lock order is
always rooms -> players (GameManager), never the reverse.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal

from .game import GameError, GameManager
from .personas import PERSONAS, Persona, persona_by_key

log = logging.getLogger(__name__)

Kind = Literal["human", "ai"]

ALIASES = (
    "Maple", "Juniper", "Rowan", "Sage", "Quinn", "River", "Wren", "Indie", "Kit", "Ellis", "Remy", "Shay",
    "Arden", "Blake", "Emery", "Harper", "Jules", "Lane", "Noor", "Oakley", "Parker", "Reese", "Sky", "Tatum",
)
SEAT_COLORS = 6  # the UI has six alias colors
MAX_HUMANS = 5
MIN_AI = 1  # the AI count is random and independent of how many humans joined,
MAX_AI = 3  # so the number of seats never tells you how many AIs there are
MAX_ROOMS = 400
LOBBY_WAIT = (6.0, 10.0)
VOTE_SECONDS = 45.0
IDLE_GAP = (8.0, 15.0)  # silence before an AI may break it
HUMAN_IDLE_SECONDS = 30.0  # nobody active -> AIs stop breaking silences
VOTE_PRESENCE_SECONDS = 120.0  # background tabs poll slowly; still wait for their votes
AI_PENDING_TIMEOUT = 45.0  # watchdog for a stuck AI turn
CLEANUP_INTERVAL = 5.0
AI_OPENS_PROBABILITY = 0.85
AI_REPLIES_TO_HUMAN = 0.9
AI_FOLLOWUP_PROBABILITY = 0.4  # chance another AI chimes in after an AI message
MENTION_WEIGHT = 6.0
RECENT_SPEAKER_WEIGHT = 0.25
MAX_ROOM_MESSAGES = 300
MAX_MESSAGES_PER_PLAYER = 60
MAX_ROOM_AI_MESSAGES = 60
FINISHED_ROOM_TTL = 600.0
POINTS_PER_CORRECT_MARK = 50
PERFECT_BONUS = 50
SEEMED_HUMAN_POINTS = 25  # per other human who judged you human
MAX_SEEMED_HUMAN_POINTS = 50


@dataclass
class Seat:
    alias: str
    color: int
    kind: Kind
    player_id: str | None = None
    nickname: str | None = None
    persona_key: str | None = None
    chattiness: float = 1.0
    last_seen: float = 0.0


@dataclass(frozen=True)
class RoomMessage:
    seq: int
    alias: str
    text: str
    sent_at: float


@dataclass
class Room:
    id: str
    created_at: float
    starts_at: float
    seats: list[Seat] = field(default_factory=list)
    started: bool = False
    ends_at: float = 0.0
    vote_ends_at: float = 0.0
    messages: list[RoomMessage] = field(default_factory=list)
    votes: dict[str, dict[str, str]] = field(default_factory=dict)  # player_id -> {alias: "ai"|"human"}
    vote_times: dict[str, float] = field(default_factory=dict)
    points: dict[str, int] = field(default_factory=dict)
    chat_closed_at: float | None = None
    finished_at: float | None = None
    ai_pending: bool = False
    ai_pending_since: float = 0.0
    sent_by: dict[str, int] = field(default_factory=dict)
    last_activity: float = 0.0
    idle_gap: float = 10.0
    last_message_at: dict[str, float] = field(default_factory=dict)

    def humans(self) -> list[Seat]:
        return [s for s in self.seats if s.kind == "human"]

    def ais(self) -> list[Seat]:
        return [s for s in self.seats if s.kind == "ai"]

    def seat_of(self, player_id: str) -> Seat | None:
        return next((s for s in self.seats if s.player_id == player_id), None)

    def seat_by_alias(self, alias: str) -> Seat | None:
        return next((s for s in self.seats if s.alias == alias), None)


@dataclass(frozen=True)
class RoomAITurn:
    room_id: str
    alias: str
    persona: Persona
    aliases: tuple[str, ...]
    transcript: tuple[tuple[str, str], ...]  # (alias, text)
    last_seq: int
    seconds_left: float


@dataclass(frozen=True)
class RoomRecord:
    room_id: str
    started_at: float
    chat_closed_at: float
    finished_at: float
    seats: tuple[Seat, ...]
    messages: tuple[RoomMessage, ...]
    votes: tuple[tuple[str, str, str], ...]  # (voter_nickname, target_alias, vote)
    points: tuple[tuple[str, int], ...]  # (nickname, points)


Action = Callable[[], None]


class RoomManager:
    def __init__(
        self,
        players: GameManager,
        *,
        room_seconds: float = 180.0,
        max_message_chars: int = 300,
        min_seconds_between_messages: float = 0.6,
        clock: Callable[[], float] = time.time,
        rng: random.Random | None = None,
        on_ai_turn: Callable[[str], None] | None = None,
        on_room_finished: Callable[[RoomRecord], None] | None = None,
    ) -> None:
        self._players = players
        self._room_seconds = room_seconds
        self._max_chars = max_message_chars
        self._min_gap = min_seconds_between_messages
        self._clock = clock
        self._rng = rng or random.Random()
        self._on_ai_turn = on_ai_turn or (lambda _rid: None)
        self._on_room_finished = on_room_finished or (lambda _rec: None)
        self._lock = threading.RLock()
        self._rooms: dict[str, Room] = {}
        self._open_room_id: str | None = None
        self._player_room: dict[str, str] = {}
        self._last_cleanup = 0.0

    # ------------------------------------------------------------- matchmaking
    def join(self, player_id: str) -> dict:
        nickname = self._players.player_nickname(player_id)  # validates the player
        actions: list[Action] = []
        try:
            with self._lock:
                self._cleanup(actions)
                current = self._current_room(player_id)
                if current is None:
                    self._seat_in_open_room(actions, player_id, nickname)
                return self._match_status(actions, player_id)
        finally:
            self._run(actions)

    def poll(self, player_id: str) -> dict:
        self._players.player_nickname(player_id)
        actions: list[Action] = []
        try:
            with self._lock:
                self._cleanup(actions)
                return self._match_status(actions, player_id)
        finally:
            self._run(actions)

    def cancel(self, player_id: str) -> None:
        self._players.player_nickname(player_id)
        with self._lock:
            room = self._current_room(player_id)
            if room is None or room.started:
                return
            room.seats = [s for s in room.seats if s.player_id != player_id]
            self._player_room.pop(player_id, None)
            if not room.seats:
                self._rooms.pop(room.id, None)
                self._open_room_id = None

    def _current_room(self, player_id: str) -> Room | None:
        room = self._rooms.get(self._player_room.get(player_id, ""))
        if room is None:
            return None
        if room.finished_at is not None or player_id in room.votes:
            self._player_room.pop(player_id, None)
            return None
        return room

    def _seat_in_open_room(self, actions: list[Action], player_id: str, nickname: str) -> None:
        now = self._clock()
        room = self._rooms.get(self._open_room_id or "")
        if room is None or room.started:
            if len(self._rooms) >= MAX_ROOMS:
                raise GameError("All rooms are busy. Try again in a minute.", 503)
            room = Room(id=uuid.uuid4().hex, created_at=now, starts_at=now + self._rng.uniform(*LOBBY_WAIT))
            self._rooms[room.id] = room
            self._open_room_id = room.id
        taken = {s.alias for s in room.seats}
        alias = self._rng.choice([a for a in ALIASES if a not in taken])
        room.seats.append(Seat(alias, 0, "human", player_id=player_id, nickname=nickname, last_seen=now))
        self._player_room[player_id] = room.id
        if len(room.humans()) >= MAX_HUMANS:
            self._start_room(actions, room)

    def _match_status(self, actions: list[Action], player_id: str) -> dict:
        room = self._current_room(player_id)
        if room is None:
            return {"status": "idle", "room_id": None}
        seat = room.seat_of(player_id)
        if seat is not None:
            seat.last_seen = self._clock()
        self._advance(actions, room)
        if not room.started:
            return {"status": "waiting", "room_id": None}
        return {"status": "matched", "room_id": room.id}

    def _start_room(self, actions: list[Action], room: Room) -> None:
        now = self._clock()
        ai_count = self._rng.randint(MIN_AI, MAX_AI)
        taken = {s.alias for s in room.seats}
        aliases = self._rng.sample([a for a in ALIASES if a not in taken], ai_count)
        personas = self._rng.sample(list(PERSONAS), min(ai_count, len(PERSONAS)))
        for i, alias in enumerate(aliases):
            persona = personas[i % len(personas)]
            chattiness = self._rng.uniform(0.6, 1.4)
            room.seats.append(Seat(alias, 0, "ai", persona_key=persona.key, chattiness=chattiness, last_seen=now))
        self._rng.shuffle(room.seats)
        for i, seat in enumerate(room.seats):
            seat.color = i % SEAT_COLORS
            seat.last_seen = now
        room.started = True
        room.ends_at = now + self._room_seconds
        room.last_activity = now
        room.idle_gap = self._rng.uniform(*IDLE_GAP)
        if self._open_room_id == room.id:
            self._open_room_id = None
        if self._rng.random() < AI_OPENS_PROBABILITY:
            self._schedule_ai(actions, room)

    # ---------------------------------------------------------------- chat
    def send_message(self, player_id: str, room_id: str, text: str) -> None:
        actions: list[Action] = []
        try:
            with self._lock:
                room, seat = self._room_for(player_id, room_id)
                now = self._clock()
                seat.last_seen = now
                self._advance(actions, room)
                if not room.started:
                    raise GameError("The chat hasn't started yet.", 409)
                if room.chat_closed_at is not None:
                    raise GameError("Chat is over. Time to vote!", 409)
                clean = " ".join(text.split())[: self._max_chars]
                if not clean:
                    raise GameError("Message is empty.")
                if room.sent_by.get(player_id, 0) >= MAX_MESSAGES_PER_PLAYER:
                    raise GameError("You've hit the message limit for this round.", 429)
                if len(room.messages) >= MAX_ROOM_MESSAGES:
                    raise GameError("That's enough messages for one round.", 429)
                last = room.last_message_at.get(player_id)
                if last is not None and now - last < self._min_gap:
                    raise GameError("Slow down a little.", 429)
                room.last_message_at[player_id] = now
                room.sent_by[player_id] = room.sent_by.get(player_id, 0) + 1
                self._append(room, seat.alias, clean)
                if not room.ai_pending and self._rng.random() < AI_REPLIES_TO_HUMAN:
                    self._schedule_ai(actions, room)
        finally:
            self._run(actions)

    def _append(self, room: Room, alias: str, text: str) -> None:
        now = self._clock()
        room.messages.append(RoomMessage(len(room.messages) + 1, alias, text, now))
        room.last_activity = now
        room.idle_gap = self._rng.uniform(*IDLE_GAP)

    def _schedule_ai(self, actions: list[Action], room: Room) -> None:
        room.ai_pending = True
        room.ai_pending_since = self._clock()
        actions.append(lambda rid=room.id: self._start_ai_turn(rid))

    def _start_ai_turn(self, room_id: str) -> None:
        try:
            self._on_ai_turn(room_id)
        except Exception:
            log.exception("Could not schedule AI turn for room %s", room_id)
            self.release_ai_turn(room_id)

    def claim_ai_turn(self, room_id: str) -> RoomAITurn | None:
        """Pick which AI might speak next and snapshot the chat for it."""
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return None
            ai_sent = sum(1 for m in room.messages if room.seat_by_alias(m.alias) in room.ais())
            if room.chat_closed_at is not None or self._clock() >= room.ends_at or ai_sent >= MAX_ROOM_AI_MESSAGES:
                room.ai_pending = False
                return None
            speaker = self._pick_speaker(room)
            persona = persona_by_key(speaker.persona_key or "") if speaker else None
            if speaker is None or persona is None:
                room.ai_pending = False
                return None
            return RoomAITurn(
                room_id=room.id,
                alias=speaker.alias,
                persona=persona,
                aliases=tuple(s.alias for s in room.seats),
                transcript=tuple((m.alias, m.text) for m in room.messages),
                last_seq=len(room.messages),
                seconds_left=max(0.0, room.ends_at - self._clock()),
            )

    def _pick_speaker(self, room: Room) -> Seat | None:
        ais = room.ais()
        if not ais:
            return None
        recent = [m.alias for m in room.messages[-2:]]
        last = room.messages[-1] if room.messages else None
        weights = []
        for seat in ais:
            weight = seat.chattiness
            if last is not None and last.alias == seat.alias:
                weight = 0.0  # don't answer yourself
            elif seat.alias in recent:
                weight *= RECENT_SPEAKER_WEIGHT
            if last is not None and re.search(rf"\b{re.escape(seat.alias)}\b", last.text, re.IGNORECASE):
                weight *= MENTION_WEIGHT
            weights.append(weight)
        if sum(weights) <= 0:
            return None
        return self._rng.choices(ais, weights=weights, k=1)[0]

    def post_ai_message(self, room_id: str, alias: str, text: str | None, snapshot_seq: int) -> bool:
        """Post an AI line (None = it chose to stay quiet). Returns True if another AI turn should follow."""
        with self._lock:
            room = self._rooms.get(room_id)
            if room is None:
                return False
            if room.chat_closed_at is not None or self._clock() >= room.ends_at:
                room.ai_pending = False
                return False
            newer = room.messages[snapshot_seq:]
            humans = {s.alias for s in room.humans()}
            newer_human = any(m.alias in humans for m in newer)
            # A reply written for an empty room is stale once someone else has spoken.
            stale_opener = snapshot_seq == 0 and bool(newer)
            if text and not stale_opener:
                self._append(room, alias, text)
            follow = newer_human or (bool(text) and self._rng.random() < AI_FOLLOWUP_PROBABILITY)
            room.ai_pending = follow
            room.ai_pending_since = self._clock()
            return follow

    def release_ai_turn(self, room_id: str) -> None:
        with self._lock:
            room = self._rooms.get(room_id)
            if room is not None:
                room.ai_pending = False

    # --------------------------------------------------------------- voting
    def vote(self, player_id: str, room_id: str, votes: dict[str, str]) -> dict:
        actions: list[Action] = []
        try:
            with self._lock:
                room, seat = self._room_for(player_id, room_id)
                seat.last_seen = self._clock()
                self._advance(actions, room)
                if room.chat_closed_at is None:
                    raise GameError("Voting opens when the chat ends.", 409)
                if room.finished_at is not None:
                    raise GameError("Voting has closed.", 409)
                if player_id in room.votes:
                    raise GameError("You already voted.", 409)
                others = {s.alias for s in room.seats if s.player_id != player_id}
                if set(votes) != others or not all(v in ("ai", "human") for v in votes.values()):
                    raise GameError("Mark every other player as human or AI.", 422)
                room.votes[player_id] = dict(votes)
                room.vote_times[player_id] = self._clock()
                self._advance(actions, room)
                return self._view(room, seat, since=len(room.messages))
        finally:
            self._run(actions)

    # ----------------------------------------------------------------- view
    def view(self, player_id: str, room_id: str, since: int = 0) -> dict:
        actions: list[Action] = []
        try:
            with self._lock:
                room, seat = self._room_for(player_id, room_id)
                seat.last_seen = self._clock()
                self._advance(actions, room)
                return self._view(room, seat, since)
        finally:
            self._run(actions)

    def _view(self, room: Room, seat: Seat, since: int) -> dict:
        now = self._clock()
        player_id = seat.player_id or ""
        if room.chat_closed_at is None:
            status, seconds_left = "chatting", max(0.0, room.ends_at - now)
        elif room.finished_at is None:
            # Nobody learns who was an AI until every vote is in.
            voted = player_id in room.votes
            status, seconds_left = ("waiting" if voted else "voting"), max(0.0, room.vote_ends_at - now)
        else:
            status, seconds_left = "revealed", 0.0
        view: dict = {
            "room_id": room.id,
            "status": status,
            "seconds_left": seconds_left,
            "round_seconds": self._room_seconds,
            "vote_seconds": VOTE_SECONDS,
            "me": seat.alias,
            "seats": [{"alias": s.alias, "color": s.color, "me": s is seat} for s in room.seats],
            "messages": [
                {"seq": m.seq, "alias": m.alias, "from": "me" if m.alias == seat.alias else "them", "text": m.text}
                for m in room.messages[max(0, since):]
            ],
            "message_count": len(room.messages),
            "player": self._players.player_stats(player_id),
            "reveal": None,
        }
        if status == "revealed":
            view["reveal"] = self._reveal(room, seat)
        return view

    def _reveal(self, room: Room, me: Seat) -> dict:
        mine = room.votes.get(me.player_id or "", {})
        seats = []
        for seat in room.seats:
            judged = [v[seat.alias] for pid, v in room.votes.items() if pid != seat.player_id and seat.alias in v]
            persona = persona_by_key(seat.persona_key or "")
            seats.append({
                "alias": seat.alias,
                "color": seat.color,
                "me": seat is me,
                "kind": seat.kind,
                "name": seat.nickname if seat.kind == "human" else (persona.name if persona else "AI"),
                "detail": persona.backstory if persona and seat.kind == "ai" else "",
                "your_vote": mine.get(seat.alias),
                "correct": (mine.get(seat.alias) == seat.kind) if seat.alias in mine else None,
                "voted_ai": sum(1 for v in judged if v == "ai"),
                "votes": len(judged),
            })
        marks = [s for s in seats if s["correct"] is not None]
        return {
            "seats": seats,
            "correct_marks": sum(1 for s in marks if s["correct"]),
            "total_marks": len(marks),
            "points": room.points.get(me.player_id or "", 0),
            "final": room.finished_at is not None,  # points and vote counts are settled
            "ai_count": len(room.ais()),
            "human_count": len(room.humans()),
        }

    # -------------------------------------------------------------- lifecycle
    def _room_for(self, player_id: str, room_id: str) -> tuple[Room, Seat]:
        self._players.player_nickname(player_id)
        room = self._rooms.get(room_id)
        seat = room.seat_of(player_id) if room else None
        if room is None or seat is None:
            raise GameError("Room not found.", 404)
        return room, seat

    def _advance(self, actions: list[Action], room: Room) -> None:
        now = self._clock()
        if not room.started:
            if now >= room.starts_at and room.humans():
                self._start_room(actions, room)
            return
        if room.ai_pending and now - room.ai_pending_since > AI_PENDING_TIMEOUT:
            log.warning("AI turn in room %s took too long; releasing it", room.id)
            room.ai_pending = False
        if room.chat_closed_at is None:
            if now >= room.ends_at:
                room.chat_closed_at = room.ends_at
                room.vote_ends_at = now + VOTE_SECONDS
                room.ai_pending = False
            elif not room.ai_pending and now - room.last_activity >= room.idle_gap and self._humans_present(room):
                room.last_activity = now
                room.idle_gap = self._rng.uniform(*IDLE_GAP)
                self._schedule_ai(actions, room)
        if room.finished_at is None and room.chat_closed_at is not None:
            present = [s for s in room.humans() if now - s.last_seen <= VOTE_PRESENCE_SECONDS]
            all_voted = all(s.player_id in room.votes for s in present)
            if all_voted or now >= room.vote_ends_at:
                self._finish(actions, room)

    def _humans_present(self, room: Room) -> bool:
        now = self._clock()
        return any(now - s.last_seen <= HUMAN_IDLE_SECONDS for s in room.humans())

    def _finish(self, actions: list[Action], room: Room) -> None:
        room.finished_at = self._clock()
        # With one human, "everyone else is an AI" is always right, so no perfect bonus or streak.
        contested = len(room.humans()) >= 2
        for seat in room.humans():
            votes = room.votes.get(seat.player_id or "")
            if votes is None:
                continue
            correct = sum(1 for alias, v in votes.items() if (t := room.seat_by_alias(alias)) and t.kind == v)
            perfect = contested and correct == len(votes)
            seemed_human = sum(
                1 for pid, v in room.votes.items() if pid != seat.player_id and v.get(seat.alias) == "human"
            )
            points = POINTS_PER_CORRECT_MARK * correct + (PERFECT_BONUS if perfect else 0)
            points += min(MAX_SEEMED_HUMAN_POINTS, SEEMED_HUMAN_POINTS * seemed_human)
            room.points[seat.player_id or ""] = points
            # Award now (lock order rooms -> players is allowed) so the totals in this view are current.
            self._players.award_room(seat.player_id or "", points, perfect)
        nick = {s.player_id: s.nickname for s in room.humans()}
        record = RoomRecord(
            room_id=room.id,
            started_at=room.ends_at - self._room_seconds,
            chat_closed_at=room.chat_closed_at or room.finished_at,
            finished_at=room.finished_at,
            seats=tuple(Seat(**vars(s)) for s in room.seats),
            messages=tuple(room.messages),
            votes=tuple(
                (nick.get(pid) or "", alias, vote) for pid, votes in room.votes.items() for alias, vote in votes.items()
            ),
            points=tuple((nick.get(pid) or "", pts) for pid, pts in room.points.items()),
        )
        actions.append(lambda: self._on_room_finished(record))

    def _cleanup(self, actions: list[Action]) -> None:
        now = self._clock()
        if now - self._last_cleanup < CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        for room in list(self._rooms.values()):
            self._advance(actions, room)
            if room.finished_at is not None and now - room.finished_at > FINISHED_ROOM_TTL:
                for seat in room.humans():
                    if self._player_room.get(seat.player_id or "") == room.id:
                        self._player_room.pop(seat.player_id or "", None)
                del self._rooms[room.id]

    @staticmethod
    def _run(actions: list[Action]) -> None:
        for action in actions:
            try:
                action()
            except Exception:
                log.exception("Room callback failed")
