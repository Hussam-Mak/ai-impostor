from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from impostor.api import create_app


@pytest.fixture
def client(harness):
    return TestClient(create_app(harness.manager, {"mode": "test"}))


def join(client, name="tester"):
    res = client.post("/api/players", json={"nickname": name})
    assert res.status_code == 200
    return res.json()["player_id"]


def test_index_and_health(client):
    assert "AI Impostor" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/health").json() == {"ok": True, "mode": "test"}


@pytest.mark.parametrize("name", ["", "x" * 21, "<script>"])
def test_bad_nicknames_are_rejected(client, name):
    assert client.post("/api/players", json={"nickname": name}).status_code == 422


def test_bad_player_id_is_rejected(client):
    assert client.post("/api/match", json={"player_id": "nope"}).status_code == 422
    assert client.post("/api/match", json={"player_id": "a" * 32}).status_code == 404


def test_full_round_against_ai(client, harness):
    pid = join(client)
    assert client.post("/api/match", json={"player_id": pid}).json()["status"] == "waiting"
    harness.clock.advance(5)
    gid = client.post("/api/match/poll", json={"player_id": pid}).json()["game_id"]

    assert client.post(f"/api/games/{gid}/messages", json={"player_id": pid, "text": "hey"}).status_code == 200
    state = client.post(f"/api/games/{gid}/state?since=0", json={"player_id": pid}).json()
    assert state["status"] == "chatting" and state["messages"][0]["text"] == "hey"

    bad = client.post(f"/api/games/{gid}/guess", json={"player_id": pid, "guess": "robot"})
    assert bad.status_code == 422
    result = client.post(f"/api/games/{gid}/guess", json={"player_id": pid, "guess": "ai"}).json()
    assert result["reveal"]["correct"] is True

    again = client.post(f"/api/games/{gid}/guess", json={"player_id": pid, "guess": "ai"})
    assert again.status_code == 409 and again.json()["detail"]

    assert client.get("/api/leaderboard").json()[0]["nickname"] == "tester"
    assert client.get("/api/stats").json()["games_finished"] == 1


def test_two_players_chat_with_each_other(client, harness):
    a = join(client, "alice")
    b = join(client, "bob")
    client.post("/api/match", json={"player_id": a})
    assert client.post("/api/match", json={"player_id": b}).json()["status"] == "waiting"
    harness.clock.advance(5)
    gid = client.post("/api/match/poll", json={"player_id": b}).json()["game_id"]
    client.post(f"/api/games/{gid}/messages", json={"player_id": a, "text": "hi bob"})
    seen_by_b = client.post(f"/api/games/{gid}/state", json={"player_id": b}).json()["messages"]
    assert seen_by_b == [{"seq": 1, "from": "them", "text": "hi bob"}]
