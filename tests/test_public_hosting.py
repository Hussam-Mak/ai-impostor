"""Behavior needed when the server is public (GitHub Pages front end + Hugging Face Space)."""

from __future__ import annotations

import random
from dataclasses import replace

from conftest import BASE_SETTINGS, SyncExecutor
from fastapi.testclient import TestClient

from impostor.ai_player import AIResponder
from impostor.api import client_key, create_app
from impostor.config import load_settings
from impostor.ratelimit import RateLimiter

PAGES = "https://hussam-mak.github.io"


class _Req:
    def __init__(self, headers, host="10.0.0.1"):
        self.headers = headers
        self.client = type("C", (), {"host": host})()


def test_spoofed_email_header_is_ignored_off_databricks():
    req = _Req({"x-forwarded-email": "victim@tamu.edu", "x-forwarded-for": "9.9.9.9"})
    assert client_key(req, on_databricks=False) == "ip:9.9.9.9"


def test_client_ip_comes_from_the_proxy_appended_entry():
    # The client can prepend fake entries; the last one is what our proxy saw.
    req = _Req({"x-forwarded-for": "1.1.1.1, 2.2.2.2, 7.7.7.7"})
    assert client_key(req, on_databricks=False, proxy_hops=1) == "ip:7.7.7.7"
    assert client_key(req, on_databricks=False, proxy_hops=2) == "ip:2.2.2.2"
    assert client_key(_Req({}), on_databricks=False) == "ip:10.0.0.1"


def test_cors_allows_only_the_configured_origin(harness):
    settings = replace(BASE_SETTINGS, allowed_origins=(PAGES,))
    client = TestClient(create_app(harness.manager, {"mode": "test"}, settings=settings))
    ok = client.options(
        "/api/players",
        headers={"Origin": PAGES, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert ok.headers.get("access-control-allow-origin") == PAGES
    evil = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers


def test_no_cors_headers_by_default(client):
    res = client.get("/api/health", headers={"Origin": PAGES})
    assert "access-control-allow-origin" not in res.headers


def test_llm_budget_falls_back_to_scripted_bot(harness):
    calls: list[int] = []

    class CountingModel:
        def complete(self, system, messages):
            calls.append(1)
            return "real llm reply"

    responder = AIResponder(
        CountingModel(), rng=random.Random(0), executor=SyncExecutor(),
        sleep=lambda _s: None, budget=RateLimiter(limit=1, window_seconds=3600),
    )
    harness.manager._on_ai_turn = responder.on_ai_turn
    responder.bind(harness.manager)
    pid, gid = harness.ai_game()
    harness.manager.release_ai_turn(gid)
    harness.manager.send_message(pid, gid, "one")
    harness.clock.advance(1)
    harness.manager.send_message(pid, gid, "two")
    assert len(calls) <= 1  # second turn is over budget and never hits the paid endpoint
    texts = [m["text"] for m in harness.manager.view_game(pid, gid)["messages"] if m["from"] == "them"]
    assert len(texts) >= 2


def test_stale_opener_is_dropped_when_human_spoke_first(harness):
    pid, gid = harness.ai_game()
    turn = harness.manager.claim_ai_turn(gid)  # opener snapshot: empty chat
    assert turn is not None and turn.last_seq == 0
    harness.manager.send_message(pid, gid, "are you a bot")
    assert harness.manager.post_ai_message(gid, "hey", turn.last_seq) is True  # go reply to them
    texts = [m["text"] for m in harness.manager.view_game(pid, gid)["messages"]]
    assert texts == ["are you a bot"]


def test_public_settings_parse_from_env(monkeypatch):
    monkeypatch.setenv("IMPOSTOR_ALLOWED_ORIGINS", f"{PAGES}/, http://localhost:8000")
    monkeypatch.setenv("IMPOSTOR_LLM_CALLS_PER_HOUR", "50")
    settings = load_settings()
    assert settings.allowed_origins == (PAGES, "http://localhost:8000")
    assert settings.llm_calls_per_hour == 50


def test_game_page_uses_relative_assets(client):
    html = client.get("/").text
    assert 'src="static/config.js"' in html and 'href="static/styles.css"' in html
    assert 'IMPOSTOR_API_BASE = ""' in client.get("/static/config.js").text
