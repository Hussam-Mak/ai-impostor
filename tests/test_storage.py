from __future__ import annotations

import json

from impostor.storage import JsonlRecorder, build_insert, iso, record_rows


def finished_record(harness):
    pid, gid = harness.ai_game("o'brien")
    harness.manager.send_message(pid, gid, "'; DROP TABLE games; --")
    harness.manager.post_ai_message(gid, "lol what", 1)
    harness.manager.submit_guess(pid, gid, "human")
    return harness.records[0]


def test_record_rows_flatten_a_game(harness):
    rows = record_rows(finished_record(harness), "endpoint-x")
    assert rows["games"][0]["opponent_type"] == "ai"
    assert rows["games"][0]["llm_endpoint"] == "endpoint-x"
    assert rows["games"][0]["message_count"] == 2
    assert [m["sender_kind"] for m in rows["messages"]] == ["human", "ai"]
    assert rows["messages"][0]["sender_nickname"] == "o'brien"
    assert rows["guesses"][0]["correct"] is False


def test_build_insert_keeps_values_out_of_sql(harness):
    rows = record_rows(finished_record(harness), "endpoint-x")["messages"]
    sql, params = build_insert("`workspace`.`ai_impostor`.`messages`", rows)
    assert "DROP TABLE" not in sql
    assert "CAST(:seq_0 AS INT)" in sql and "CAST(:sent_at_1 AS TIMESTAMP)" in sql
    values = {name: value for name, value, _t in params}
    assert values["text_0"] == "'; DROP TABLE games; --"
    assert values["sender_nickname_1"] is None


def test_booleans_are_sql_literals(harness):
    rows = record_rows(finished_record(harness), "e")["guesses"]
    _sql, params = build_insert("t", rows)
    assert ("correct_0", "false", "BOOLEAN") in params


def test_iso_is_utc():
    assert iso(0) == "1970-01-01T00:00:00.000Z"


def test_jsonl_recorder_appends_lines(tmp_path, harness):
    recorder = JsonlRecorder(str(tmp_path), "e")
    record = finished_record(harness)
    recorder.record(record)
    recorder.record(record)
    lines = (tmp_path / "games.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["rows"]["games"][0]["game_id"] == record.game_id
