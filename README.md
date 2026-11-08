# AI Impostor

**Chat with a stranger for two minutes. Then decide: human, or AI?**

**Play (no sign-up):** https://hussam-mak.github.io/ai-impostor/play/ · **Project site:** https://hussam-mak.github.io/ai-impostor/ · Workspace version: https://ai-impostor-7474657692011817.aws.databricksapps.com

AI Impostor is a Turing-test game built entirely on Databricks. Each round pairs you with either another
player or an LLM pretending to be a person. You chat, you guess, and every message and verdict lands in
Unity Catalog, where a model learns to spot the impostor and is scored against the players.

## How it uses Databricks

| Piece | Databricks feature |
| --- | --- |
| The game (web UI + API) | **Databricks Apps** (FastAPI, `app/`) |
| The impostor | **Foundation Model APIs / Model Serving** (`databricks-meta-llama-3-3-70b-instruct` by default), with four human personas, typos and typing delays |
| Game logs | **Unity Catalog Delta tables** `games`, `messages`, `guesses`, written through a **SQL warehouse** with parameterized SQL |
| Analytics | Notebook `01_game_analytics` builds UC views: detection accuracy, persona fool rate, accuracy vs. chat length, AI vs. human writing style. Ready for an **AI/BI dashboard** or **Genie** space |
| "Can a model beat people?" | Notebook `02_train_ai_detector` trains a text classifier with **MLflow**, registers it in the **UC model registry**, and compares it with player accuracy on held-out games |
| Deploy + scheduling | **Asset Bundle** (`databricks.yml`) with the app, a setup job, and an hourly insights **Job** |

```
player ──► Databricks App (FastAPI) ──► Model Serving (LLM impostor)
                     │
                     └─► SQL warehouse ──► UC Delta tables ──► analytics views ─► AI/BI dashboard
                                                       └──────► MLflow detector ─► UC model registry
```

## Deploy to Databricks

Works on Databricks Free Edition (catalog `workspace`) or any workspace with Apps and Foundation Model APIs.

1. Install the Databricks CLI (v0.250+) and log in:

   ```bash
   winget install Databricks.DatabricksCLI
   ```

   ```bash
   databricks auth login --host https://<your-workspace>.cloud.databricks.com
   ```

2. Find a SQL warehouse ID (SQL Warehouses → your warehouse → Connection details), then from this folder:

   ```bash
   databricks bundle deploy --var warehouse_id=<warehouse-id>
   ```

3. Create the tables and grant the app access, then start the app:

   ```bash
   databricks bundle run impostor_setup --var warehouse_id=<warehouse-id>
   ```

   ```bash
   databricks bundle run ai_impostor --var warehouse_id=<warehouse-id>
   ```

   The app URL is printed and shown under **Compute → Apps → ai-impostor**.

4. After people have played, refresh analytics and train the detector (or unpause its hourly schedule):

   ```bash
   databricks bundle run impostor_insights --var warehouse_id=<warehouse-id>
   ```

Options (pass with `--var name=value`): `catalog` (default `workspace`), `schema` (default `ai_impostor`),
`llm_endpoint` (any chat endpoint listed under **Serving**). If you change `catalog` or `schema`, also change
them in `app/app.yaml`.

## Public deployment (anyone can play)

Databricks Apps always require a workspace login, so the public version splits in two:

| Piece | Where | Notes |
| --- | --- | --- |
| Game page | GitHub Pages `/play/` | Built by `.github/workflows/pages.yml` from `app/static`; server address in `pages/config.js` |
| Game server | Hugging Face Docker Space | `deploy/huggingface/`: builds from this repo; same FastAPI app |
| AI impostor, logs, ML | Databricks | Model Serving, Unity Catalog, MLflow, same as above |

Set up the Space once:

1. Create a free account at huggingface.co, then **New Space** → name `ai-impostor`, SDK **Docker** (blank), public.
2. Add the two files from `deploy/huggingface/` (`Dockerfile`, `README.md`) to the Space.
3. Space **Settings → Variables and secrets**: `DATABRICKS_HOST` (variable), `DATABRICKS_TOKEN` (secret; a personal
   access token with an expiry), optionally `DATABRICKS_WAREHOUSE_ID` to log games to Unity Catalog.
4. If your Hugging Face username isn't `hussammak`, update `pages/config.js` to `https://<username>-ai-impostor.hf.space`.

Public-server safeguards: CORS limited to the Pages site, per-IP rate limits that ignore spoofable headers,
an hourly cap on LLM calls (`IMPOSTOR_LLM_CALLS_PER_HOUR`, default 2000; over it the scripted bot answers),
and caps on players, games and messages. Free Spaces sleep when idle; the game page shows "waking up" until
the server answers.

## Run locally

Without Databricks credentials the game runs offline with a scripted mock AI and logs to `local_data/games.jsonl`.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r app/requirements.txt pytest httpx pytest-cov
```

```bash
.venv/Scripts/python app/main.py
```

Open http://localhost:8000. Open a second browser tab to play against yourself as a "human" stranger.
If you are logged in with the Databricks CLI, set `DATABRICKS_CONFIG_PROFILE` and the local app uses the real
LLM endpoint; set `DATABRICKS_WAREHOUSE_ID` too to log into Delta.

Tests (64):

```bash
.venv/Scripts/python -m pytest -q --cov=impostor
```

## Game rules

- Matchmaking waits 3–9 seconds (random, so timing doesn't give the answer away). If another player is
  waiting, you're paired with them 60% of the time; otherwise you get the AI.
- 2-minute chat, 300 characters per message. You can lock in a guess early.
- Correct guess: 100 points, +25 per streak step (up to +100). Wrong guess resets the streak.
- In human-vs-human rounds, both players guess about each other, so you score by spotting humans *and*
  by seeming human yourself.

## Settings

| Env var | Default | Meaning |
| --- | --- | --- |
| `LLM_ENDPOINT` | `databricks-meta-llama-3-3-70b-instruct` | Serving endpoint for the impostor |
| `DATABRICKS_WAREHOUSE_ID` | – | Warehouse for Delta logging (unset = local JSONL) |
| `IMPOSTOR_CATALOG` / `IMPOSTOR_SCHEMA` | `workspace` / `ai_impostor` | Where tables live |
| `IMPOSTOR_ROUND_SECONDS` | `120` | Chat length |
| `IMPOSTOR_HUMAN_MATCH_PROBABILITY` | `0.6` | Chance to pair with a waiting human |
| `IMPOSTOR_MATCH_WAIT_MIN` / `_MAX` | `3` / `9` | Matchmaking wait range (seconds) |
| `IMPOSTOR_OFFLINE` | – | `1` forces the mock AI |

## Limits

- Game state is in memory in a single app process; restarting the app ends live games (finished games are
  already saved in Delta).
- Players are anonymous: a nickname plus a random per-tab token. No sign-in beyond the workspace's own app access.

## Project layout

```
app/                 Databricks App source (deployed as-is)
  main.py            entry point
  app.yaml           runtime config + resource bindings
  impostor/          game engine, AI player, Delta storage, API
  static/            chat UI (HTML/CSS/JS, no build step)
notebooks/           00 setup tables + grants · 01 analytics views · 02 MLflow AI detector
resources/           bundle resources: app, jobs
databricks.yml       Asset Bundle
tests/               pytest suite
docs/                GitHub Pages project site (static)
pages/               Pages build config (public server URL)
deploy/huggingface/  public game server (Hugging Face Space)
```
