"""The server must actually connect to Databricks when credentials are set.

Regression: an unsupported WorkspaceClient() argument made every deployment
silently fall back to the offline mock AI. These tests check the call against
the real SDK signatures without touching the network.
"""

from __future__ import annotations

import inspect

import databricks.sdk
import databricks.sdk.core

from impostor.api import LLM_HTTP_TIMEOUT_SECONDS, _workspace_client


def test_workspace_client_call_matches_the_real_sdk(monkeypatch):
    real_client, real_config = databricks.sdk.WorkspaceClient, databricks.sdk.core.Config
    seen: dict = {}

    class FakeConfig:
        def __init__(self, **kwargs):
            inspect.signature(real_config.__init__).bind(None, **kwargs)  # TypeError if unsupported
            seen["config"] = kwargs

    class FakeClient:
        def __init__(self, **kwargs):
            inspect.signature(real_client.__init__).bind(None, **kwargs)
            seen["client"] = kwargs

    monkeypatch.delenv("IMPOSTOR_OFFLINE", raising=False)
    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", FakeClient)
    monkeypatch.setattr(databricks.sdk.core, "Config", FakeConfig)

    assert isinstance(_workspace_client(), FakeClient)
    assert seen["config"] == {"http_timeout_seconds": LLM_HTTP_TIMEOUT_SECONDS}
    assert isinstance(seen["client"]["config"], FakeConfig)


def test_offline_flag_skips_databricks(monkeypatch):
    monkeypatch.setenv("IMPOSTOR_OFFLINE", "1")
    assert _workspace_client() is None
