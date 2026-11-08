"""Runtime settings, read once from environment variables.

On Databricks Apps these come from app.yaml (some via resource bindings).
Locally they fall back to safe defaults so the game runs without a workspace.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _identifier(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not _IDENTIFIER.match(value):
        raise ValueError(f"{name} must be a plain SQL identifier, got {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    round_seconds: float
    match_wait_min: float
    match_wait_max: float
    human_match_probability: float
    partner_idle_seconds: float
    max_message_chars: int
    min_seconds_between_messages: float
    llm_endpoint: str
    warehouse_id: str | None
    catalog: str
    schema: str
    local_data_dir: str


def load_settings() -> Settings:
    match_min = _float("IMPOSTOR_MATCH_WAIT_MIN", 3.0)
    match_max = _float("IMPOSTOR_MATCH_WAIT_MAX", 9.0)
    if match_max < match_min:
        raise ValueError("IMPOSTOR_MATCH_WAIT_MAX must be >= IMPOSTOR_MATCH_WAIT_MIN")
    probability = _float("IMPOSTOR_HUMAN_MATCH_PROBABILITY", 0.6)
    if not 0.0 <= probability <= 1.0:
        raise ValueError("IMPOSTOR_HUMAN_MATCH_PROBABILITY must be between 0 and 1")

    warehouse = os.getenv("DATABRICKS_WAREHOUSE_ID", "").strip() or None
    return Settings(
        round_seconds=_float("IMPOSTOR_ROUND_SECONDS", 120.0),
        match_wait_min=match_min,
        match_wait_max=match_max,
        human_match_probability=probability,
        partner_idle_seconds=_float("IMPOSTOR_PARTNER_IDLE_SECONDS", 20.0),
        max_message_chars=int(_float("IMPOSTOR_MAX_MESSAGE_CHARS", 300)),
        min_seconds_between_messages=_float("IMPOSTOR_MIN_SECONDS_BETWEEN_MESSAGES", 0.6),
        llm_endpoint=os.getenv("LLM_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct").strip(),
        warehouse_id=warehouse,
        catalog=_identifier("IMPOSTOR_CATALOG", "workspace"),
        schema=_identifier("IMPOSTOR_SCHEMA", "ai_impostor"),
        local_data_dir=os.getenv("IMPOSTOR_LOCAL_DATA_DIR", "local_data"),
    )
