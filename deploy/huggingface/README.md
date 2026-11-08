---
title: AI Impostor
emoji: 🕵️
colorFrom: red
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Chat with a stranger, then guess human or AI
---

# AI Impostor game server

Public server for [AI Impostor](https://hussam-mak.github.io/ai-impostor/). The game page lives on GitHub Pages;
this Space runs the matchmaking and calls Databricks Model Serving for the AI impostor.
Code: https://github.com/Hussam-Mak/ai-impostor

## Space settings → Variables and secrets

| Name | Type | Value |
| --- | --- | --- |
| `DATABRICKS_HOST` | Variable | `https://dbc-788fee3e-1b59.cloud.databricks.com` |
| `DATABRICKS_TOKEN` | **Secret** | A Databricks personal access token (set an expiry, e.g. 30 days) |
| `DATABRICKS_WAREHOUSE_ID` | Variable | Your SQL warehouse ID, to log games to Unity Catalog (optional) |
| `LLM_ENDPOINT` | Variable | Optional, defaults to `databricks-meta-llama-3-3-70b-instruct` |

To pick up new commits from GitHub: Settings → **Factory rebuild**.
