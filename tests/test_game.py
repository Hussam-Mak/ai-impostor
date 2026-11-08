from __future__ import annotations

import pytest

from impostor.game import AI_SENDER, BASE_POINTS, STREAK_BONUS, GameError


def test_lone_player_is_matched_with_ai_after_wait(harness):
    pid = harness.manager.register_player("solo")
    assert harness.manager.request_match(pid)["status"] == "waiting"
    harness.clock.advance(1)
    assert harness.manager.poll_match(pid)["status"] == "waiting"
    harness.clock.advance(5)
    status = harness.manager.poll_match(pid)
    assert status["status"] == "matched"
    view = harness.manager.view_game(pid, status["game_id"])
    assert view["status"] == "chatting"
    assert view["reveal"] is None
    assert "opponent_type" not in view  # never leak the answer during the chat


def test_two_waiting_players_are_paired_as_humans(harness):
    a, b, game_id = harness.human_game()
    assert harness.manager.poll_match(a) == {"status": "matched", "game_id": game_id}
    assert harness.ai_turns == []


def test_zero_human_probability_never_pairs_humans(make_harness):
    h = make_harness(human_match_probability=0.0)
    a = h.manager.register_player("a")
    b = h.manager.register_player("b")
    h.manager.request_match(a)
    assert h.manager.request_match(b)["status"] == "waiting"
    h.clock.advance(3)
    assert h.manager.poll_match(b)["status"] == "matched"
    assert h.manager.poll_match(a)["status"] == "matched"
    assert h.manager.poll_match(a)["game_id"] != h.manager.poll_match(b)["game_id"]


def test_cancel_removes_player_from_queue(harness):
    a = harness.manager.register_player("a")
    harness.manager.request_match(a)
    harness.manager.cancel_match(a)
    harness.clock.advance(10)
    assert harness.manager.poll_match(a)["status"] == "idle"


def test_human_message_schedules_one_ai_turn_while_pending(harness):
    pid, gid = harness.ai_game()
    harness.ai_turns.clear()
    harness.manager.release_ai_turn(gid)  # ignore a possible opening turn
    harness.manager.send_message(pid, gid, "hello")
    harness.clock.advance(1)
    harness.manager.send_message(pid, gid, "you there?")
    assert harness.ai_turns == [gid]


def test_post_ai_message_reports_newer_human_messages(harness):
    pid, gid = harness.ai_game()
    harness.manager.release_ai_turn(gid)
    harness.manager.send_message(pid, gid, "hi")
    turn = harness.manager.claim_ai_turn(gid)
    assert turn is not None and turn.history[-1] == (False, "hi")
    harness.clock.advance(1)
    harness.manager.send_message(pid, gid, "hello??")
    assert harness.manager.post_ai_message(gid, "hey sorry", turn.last_seq) is True
    view = harness.manager.view_game(pid, gid)
    assert [m["text"] for m in view["messages"]] == ["hi", "hello??", "hey sorry"]
    assert view["messages"][-1]["from"] == "them"


def test_view_since_returns_only_new_messages(harness):
    pid, gid = harness.ai_game()
    harness.manager.send_message(pid, gid, "one")
    harness.clock.advance(1)
    harness.manager.send_message(pid, gid, "two")
    assert [m["text"] for m in harness.manager.view_game(pid, gid, since=1)["messages"]] == ["two"]


def test_messages_are_trimmed_and_rate_limited(harness):
    pid, gid = harness.ai_game()
    with pytest.raises(GameError):
        harness.manager.send_message(pid, gid, "   ")
    harness.manager.send_message(pid, gid, "x" * 999)
    assert len(harness.manager.view_game(pid, gid)["messages"][0]["text"]) == 300
    with pytest.raises(GameError) as err:
        harness.manager.send_message(pid, gid, "too fast")
    assert err.value.status_code == 429


def test_chat_closes_when_timer_runs_out(harness):
    pid, gid = harness.ai_game()
    harness.clock.advance(121)
    view = harness.manager.view_game(pid, gid)
    assert view["status"] == "guessing"
    assert view["closed_reason"] == "timer"
    with pytest.raises(GameError):
        harness.manager.send_message(pid, gid, "late")
    assert harness.manager.post_ai_message(gid, "late reply", 0) is False


def test_correct_guesses_build_a_streak_bonus(harness):
    pid, gid = harness.ai_game()
    first = harness.manager.submit_guess(pid, gid, "ai")
    assert first["status"] == "revealed"
    assert first["reveal"]["correct"] is True
    assert first["reveal"]["points"] == BASE_POINTS
    assert first["reveal"]["opponent_type"] == "ai"

    harness.clock.advance(1)
    status = harness.manager.request_match(pid)
    harness.clock.advance(5)
    gid2 = harness.manager.poll_match(pid)["game_id"]
    assert gid2 and gid2 != gid and status["status"] == "waiting"
    second = harness.manager.submit_guess(pid, gid2, "ai")
    assert second["reveal"]["points"] == BASE_POINTS + STREAK_BONUS
    assert second["player"]["streak"] == 2


def test_wrong_guess_resets_streak_and_scores_nothing(harness):
    pid, gid = harness.ai_game()
    view = harness.manager.submit_guess(pid, gid, "human")
    assert view["reveal"]["correct"] is False
    assert view["reveal"]["points"] == 0
    assert view["player"]["streak"] == 0
    with pytest.raises(GameError):
        harness.manager.submit_guess(pid, gid, "ai")


def test_ai_game_is_recorded_after_guess(harness):
    pid, gid = harness.ai_game()
    harness.manager.send_message(pid, gid, "hi")
    harness.manager.post_ai_message(gid, "yo", 1)
    harness.manager.submit_guess(pid, gid, "ai")
    assert len(harness.records) == 1
    record = harness.records[0]
    assert record.opponent_type == "ai" and record.persona_key
    assert [m.sender for m in record.messages] == [pid, AI_SENDER]
    assert record.closed_reason == "early_guess"


def test_human_game_finishes_when_both_guess(harness):
    a, b, gid = harness.human_game()
    harness.manager.send_message(a, gid, "hey bob")
    view_a = harness.manager.submit_guess(a, gid, "human")
    assert view_a["reveal"]["opponent_name"] == "bob"
    assert harness.records == []
    assert harness.manager.view_game(b, gid)["status"] == "guessing"
    view_b = harness.manager.submit_guess(b, gid, "ai")
    assert view_b["reveal"]["correct"] is False
    assert len(harness.records) == 1
    assert harness.manager.stats()["spot_the_human_accuracy"] == 0.5


def test_idle_partner_closes_the_chat(harness):
    a, b, gid = harness.human_game()
    harness.clock.advance(10)
    harness.manager.view_game(a, gid)
    harness.clock.advance(15)  # b has been silent for 25s
    view = harness.manager.view_game(a, gid)
    assert view["status"] == "guessing"
    assert view["closed_reason"] == "partner_ended"  # same wording an AI exit gets


def test_unguessed_game_finishes_after_grace_period(harness):
    a, b, gid = harness.human_game()
    harness.manager.submit_guess(a, gid, "human")
    harness.clock.advance(61)
    harness.manager.view_game(a, gid)
    assert len(harness.records) == 1


def test_unknown_player_and_foreign_game_are_rejected(harness):
    with pytest.raises(GameError) as err:
        harness.manager.request_match("f" * 32)
    assert err.value.status_code == 404
    _pid, gid = harness.ai_game()
    stranger = harness.manager.register_player("stranger")
    with pytest.raises(GameError):
        harness.manager.view_game(stranger, gid)


def test_leaderboard_and_stats(harness):
    pid, gid = harness.ai_game("ace")
    harness.manager.submit_guess(pid, gid, "ai")
    board = harness.manager.leaderboard()
    assert board[0]["nickname"] == "ace" and board[0]["score"] == BASE_POINTS
    stats = harness.manager.stats()
    assert stats["games_finished"] == 1
    assert stats["spot_the_ai_accuracy"] == 1.0
    assert stats["ai_fool_rate"] == 0.0
