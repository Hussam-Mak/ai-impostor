from __future__ import annotations

import random
from dataclasses import replace

import pytest

from impostor.config import Settings
from impostor import game as game_module
from impostor.game import GameManager, GameRecord


class FakeClock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class SyncExecutor:
    """Runs submitted work immediately, so AI turns are deterministic in tests."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


BASE_SETTINGS = Settings(
    round_seconds=120.0,
    match_wait_min=3.0,
    match_wait_max=3.0,
    human_match_probability=1.0,
    partner_idle_seconds=20.0,
    max_message_chars=300,
    min_seconds_between_messages=0.5,
    llm_endpoint="test-endpoint",
    warehouse_id=None,
    catalog="workspace",
    schema="ai_impostor",
    local_data_dir="local_data",
)


class Harness:
    def __init__(self, **overrides) -> None:
        game_module.AI_LEAVES_EARLY_PROBABILITY = 0.0  # tests opt in explicitly
        self.clock = FakeClock()
        self.ai_turns: list[str] = []
        self.records: list[GameRecord] = []
        self.settings = replace(BASE_SETTINGS, **overrides)
        self.manager = GameManager(
            self.settings,
            clock=self.clock,
            rng=random.Random(7),
            on_ai_turn=self.ai_turns.append,
            on_game_finished=self.records.append,
        )

    def ai_game(self, nickname: str = "solo") -> tuple[str, str]:
        pid = self.manager.register_player(nickname)
        assert self.manager.request_match(pid)["status"] == "waiting"
        self.clock.advance(self.settings.match_wait_max)
        status = self.manager.poll_match(pid)
        assert status["status"] == "matched"
        return pid, status["game_id"]

    def human_game(self) -> tuple[str, str, str]:
        a = self.manager.register_player("alice")
        b = self.manager.register_player("bob")
        self.manager.request_match(a)
        assert self.manager.request_match(b)["status"] == "waiting"  # held, like an AI match
        self.clock.advance(self.settings.match_wait_max)
        status = self.manager.poll_match(b)
        assert status["status"] == "matched"
        assert self.manager.poll_match(a) == status
        return a, b, status["game_id"]


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.fixture
def make_harness():
    return Harness
