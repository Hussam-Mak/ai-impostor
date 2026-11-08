"""Regression tests for issues found in the ECC python and security reviews."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import SyncExecutor

from impostor import game as game_module
from impostor.api import SECURITY_HEADERS, client_key, create_app
from impostor.game import GameError
from impostor.ratelimit import RateLimiter
from impostor.storage import DeltaRecorder


# ---------------------------------------------------------------- fairness
def test_human_match_is_not_visible_instantly(harness):
    a = harness.manager.register_player("a")
    b = harness.manager.register_player("b")
    harness.manager.request_match(a)
    assert harness.manager.request_match(b)["status"] == "waiting"
    harness.clock.advance(1)
    assert harness.manager.poll_match(b)["status"] == "waiting"
    assert harness.manager.poll_match(a)["status"] == "waiting"


def test_waiter_close_to_deadline_is_not_paired(make_harness):
    h = make_harness(match_wait_min=3.0, match_wait_max=3.0)
    a = h.manager.register_player("a")
    h.manager.request_match(a)
    h.clock.advance(1)  # a has 2s left, less than the 3s minimum wait
    b = h.manager.register_player("b")
    assert h.manager.request_match(b)["status"] == "waiting"
    h.clock.advance(2)
    game_a = h.manager.poll_match(a)["game_id"]
    h.clock.advance(1)
    game_b = h.manager.poll_match(b)["game_id"]
    assert game_a and game_b and game_a != game_b


def test_ai_can_leave_early_with_neutral_reason(make_harness, monkeypatch):
    h = make_harness()
    monkeypatch.setattr(game_module, "AI_LEAVES_EARLY_PROBABILITY", 1.0)
    pid, gid = h.ai_game()
    h.clock.advance(110)
    view = h.manager.view_game(pid, gid)
    assert view["status"] == "guessing"
    assert view["closed_reason"] == "partner_ended"


def test_partner_early_guess_looks_like_partner_ended(harness):
    a, b, gid = harness.human_game()
    harness.manager.submit_guess(a, gid, "human")
    assert harness.manager.view_game(b, gid)["closed_reason"] == "partner_ended"
    assert harness.manager.view_game(a, gid)["closed_reason"] == "you_guessed"


# --------------------------------------------------------------- robustness
def test_game_is_recorded_even_when_the_call_raises(harness):
    pid, gid = harness.ai_game()
    harness.clock.advance(200)  # timer and grace period both passed, nobody polled
    with pytest.raises(GameError):
        harness.manager.send_message(pid, gid, "late")
    assert len(harness.records) == 1


def test_failing_recorder_does_not_block_later_ai_turns(harness):
    def boom(_record):
        raise TypeError("bad record")

    harness.manager._on_game_finished = boom
    pid, gid = harness.ai_game()
    harness.manager.submit_guess(pid, gid, "ai")  # recorder raises in a callback; the call still works
    pid2, gid2 = harness.ai_game("second")
    harness.manager.release_ai_turn(gid2)
    harness.manager.send_message(pid2, gid2, "hi")
    assert gid2 in harness.ai_turns


def test_failing_ai_scheduler_releases_pending(harness):
    calls: list[str] = []

    def flaky(gid):
        calls.append(gid)
        raise RuntimeError("pool shut down")

    harness.manager._on_ai_turn = flaky
    pid, gid = harness.ai_game()
    harness.manager.release_ai_turn(gid)
    calls.clear()  # ignore a possible opening turn
    harness.manager.send_message(pid, gid, "one")
    harness.clock.advance(1)
    harness.manager.send_message(pid, gid, "two")
    assert calls.count(gid) == 2  # not stuck pending after the first failure


def test_sending_a_message_counts_as_presence(harness):
    a, b, gid = harness.human_game()
    harness.clock.advance(19)
    harness.manager.view_game(a, gid)
    harness.manager.send_message(b, gid, "still here")
    harness.clock.advance(5)
    assert harness.manager.view_game(a, gid)["status"] == "chatting"


# ------------------------------------------------------------------- limits
def test_ai_message_budget(harness):
    pid, gid = harness.ai_game()
    for i in range(game_module.MAX_AI_MESSAGES_PER_GAME):
        harness.manager.post_ai_message(gid, f"m{i}", 0)
    assert harness.manager.claim_ai_turn(gid) is None


def test_player_cap(harness, monkeypatch):
    monkeypatch.setattr(game_module, "MAX_PLAYERS", 2)
    harness.manager.register_player("a")
    harness.manager.register_player("b")
    with pytest.raises(GameError) as err:
        harness.manager.register_player("c")
    assert err.value.status_code == 503


def test_stats_use_counters_not_a_growing_list(harness):
    pid, gid = harness.ai_game()
    harness.manager.submit_guess(pid, gid, "human")
    assert harness.manager.stats()["ai_fool_rate"] == 1.0
    assert not hasattr(harness.manager, "_finished")


def test_rate_limiter_window():
    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    assert limiter.allow("k") and limiter.allow("k")
    assert not limiter.allow("k")
    now[0] = 11
    assert limiter.allow("k")


def test_join_is_rate_limited_and_security_headers_are_set(harness):
    client = TestClient(create_app(harness.manager, {"mode": "test"}, join_limiter=RateLimiter(1, 60)))
    first = client.post("/api/players", json={"nickname": "a"})
    assert first.status_code == 200
    for name in SECURITY_HEADERS:
        assert name in first.headers
    assert client.post("/api/players", json={"nickname": "b"}).status_code == 429


def test_client_key_prefers_the_databricks_user():
    class Req:
        headers = {"x-forwarded-email": "Me@TAMU.edu", "x-forwarded-for": "1.2.3.4"}
        client = None

    assert client_key(Req()) == "user:me@tamu.edu"


# ------------------------------------------------------------------ storage
class _Status:
    def __init__(self, state):
        self.state = state
        self.error = None


class _Response:
    def __init__(self, state):
        self.status = _Status(state)
        self.statement_id = "s1"


class _StatementApi:
    def __init__(self, states):
        self.states = list(states)
        self.sql: list[str] = []

    def execute_statement(self, statement, warehouse_id, parameters=None, wait_timeout=None):
        self.sql.append(statement)
        return _Response(self.states.pop(0))

    def get_statement(self, statement_id):
        return _Response(self.states.pop(0))


class _Client:
    def __init__(self, states):
        self.statement_execution = _StatementApi(states)


def test_delta_recorder_waits_for_cold_warehouse_and_writes_games_last(harness):
    from databricks.sdk.service.sql import StatementState as S

    pid, gid = harness.ai_game()
    harness.manager.send_message(pid, gid, "hi")
    harness.manager.submit_guess(pid, gid, "ai")
    client = _Client([S.PENDING, S.RUNNING, S.SUCCEEDED, S.SUCCEEDED, S.SUCCEEDED])
    recorder = DeltaRecorder(client, "wh", "workspace", "ai_impostor", "e", sleep=lambda _s: None)
    recorder._executor = SyncExecutor()
    recorder.record(harness.records[0])
    tables = [sql.split("`")[5] for sql in client.statement_execution.sql]
    assert tables == ["messages", "guesses", "games"]
    assert client.statement_execution.states == []  # polled through PENDING and RUNNING
