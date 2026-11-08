from __future__ import annotations

import random

from conftest import SyncExecutor

from impostor.ai_player import (
    MAX_DELAY,
    MAX_REPLY_CHARS,
    AIResponder,
    MockChatModel,
    build_system_prompt,
    humanize,
    to_model_messages,
    typing_delay,
)
from impostor.personas import PERSONAS, persona_by_key

LOWER = next(p for p in PERSONAS if p.lowercase)
UPPER = next(p for p in PERSONAS if not p.lowercase)


def no_typos(persona):
    from dataclasses import replace

    return replace(persona, typo_rate=0.0)


def test_humanize_replaces_ai_giveaways():
    text = humanize("As an AI language model, I cannot do that.", no_typos(UPPER), random.Random(1))
    assert "ai" not in text.lower().split()
    assert "language model" not in text.lower()


def test_humanize_lowercases_strips_prefix_and_quotes():
    persona = no_typos(LOWER)
    text = humanize(f'"{persona.name}: Hey There"', persona, random.Random(1))
    assert text == "hey there"


def test_humanize_caps_length():
    text = humanize("word " * 200, no_typos(UPPER), random.Random(1))
    assert len(text) <= MAX_REPLY_CHARS


def test_typo_changes_but_keeps_letters():
    from dataclasses import replace

    persona = replace(UPPER, typo_rate=1.0)
    text = humanize("Totally agree with that", persona, random.Random(3))
    assert sorted(text.replace(" ", "")) == sorted("Totally agree with that".replace(" ", ""))


def test_model_messages_merge_and_end_with_user():
    msgs = to_model_messages(((False, "hi"), (False, "hello?"), (True, "hey")))
    assert msgs[0] == ("user", "hi\nhello?")
    assert msgs[1] == ("assistant", "hey")
    assert msgs[-1][0] == "user"


def test_model_messages_for_opening_turn():
    msgs = to_model_messages(())
    assert len(msgs) == 1 and msgs[0][0] == "user"


def test_system_prompt_mentions_persona_and_secrecy():
    persona = PERSONAS[0]
    prompt = build_system_prompt(persona, 90)
    assert persona.name in prompt and "Never reveal" in prompt


def test_typing_delay_is_bounded():
    rng = random.Random(0)
    assert typing_delay("x" * 500, rng, opening=False) <= MAX_DELAY
    assert 2.0 <= typing_delay("hi", rng, opening=True) <= 6.0


def test_mock_model_denies_being_a_bot():
    assert "bot" in MockChatModel(random.Random(0)).complete("", [("user", "are you a bot?")])


def test_responder_replies_through_the_game(harness):
    class EchoModel:
        def complete(self, system, messages):
            return "Same lol"

    slept: list[float] = []
    responder = AIResponder(EchoModel(), rng=random.Random(0), executor=SyncExecutor(), sleep=slept.append)
    harness.manager._on_ai_turn = responder.on_ai_turn
    responder.bind(harness.manager)

    pid, gid = harness.ai_game()
    harness.manager.release_ai_turn(gid)
    harness.manager.send_message(pid, gid, "hi")
    texts = [m["text"].lower() for m in harness.manager.view_game(pid, gid)["messages"]]
    assert texts[-1].startswith("same") or texts[-1].startswith("sa")  # typo may swap letters
    assert slept and slept[-1] > 0


def test_responder_survives_model_errors(harness):
    class BrokenModel:
        def complete(self, system, messages):
            raise RuntimeError("endpoint down")

    responder = AIResponder(BrokenModel(), rng=random.Random(0), executor=SyncExecutor(), sleep=lambda _s: None)
    harness.manager._on_ai_turn = responder.on_ai_turn
    responder.bind(harness.manager)
    pid, gid = harness.ai_game()
    harness.manager.release_ai_turn(gid)
    harness.manager.send_message(pid, gid, "hi")
    messages = harness.manager.view_game(pid, gid)["messages"]
    assert messages[-1]["from"] == "them"  # a fallback reply, not silence


def test_persona_lookup():
    assert persona_by_key(PERSONAS[1].key) == PERSONAS[1]
    assert persona_by_key("nope") is None
