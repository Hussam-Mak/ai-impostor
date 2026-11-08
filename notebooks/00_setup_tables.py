# Databricks notebook source
# MAGIC %md
# MAGIC # AI Impostor · 00 Setup
# MAGIC Creates the Unity Catalog schema and the three Delta tables the app writes to,
# MAGIC then grants the app's service principal access. Safe to re-run.

# COMMAND ----------

import re

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "ai_impostor")
dbutils.widgets.text("app_service_principal", "")

catalog = dbutils.widgets.get("catalog").strip()
schema = dbutils.widgets.get("schema").strip()
app_sp = dbutils.widgets.get("app_service_principal").strip()

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
for name, value in {"catalog": catalog, "schema": schema}.items():
    if not IDENT.match(value):
        raise ValueError(f"{name} must be a plain identifier, got {value!r}")
if app_sp and not re.fullmatch(r"[0-9a-fA-F-]{36}", app_sp):
    raise ValueError("app_service_principal must be the app's service principal application ID (a UUID)")

fq = f"`{catalog}`.`{schema}`"
print(f"Target schema: {fq}")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {fq} COMMENT 'AI Impostor game logs'")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.games (
  game_id STRING NOT NULL, opponent_type STRING, persona STRING, llm_endpoint STRING,
  started_at TIMESTAMP, chat_closed_at TIMESTAMP, finished_at TIMESTAMP,
  closed_reason STRING, player_count INT, message_count INT
) COMMENT 'One row per finished game'
""")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.messages (
  game_id STRING NOT NULL, seq INT, sender_kind STRING, sender_nickname STRING,
  text STRING, sent_at TIMESTAMP
) COMMENT 'Every chat message; sender_kind is human or ai'
""")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.guesses (
  game_id STRING NOT NULL, opponent_type STRING, persona STRING, player_nickname STRING,
  guess STRING, correct BOOLEAN, points INT, guessed_at TIMESTAMP
) COMMENT 'Each player verdict: was the stranger an AI or a human?'
""")

display(spark.sql(f"SHOW TABLES IN {fq}"))

# COMMAND ----------

# MAGIC %md
# MAGIC ### Grant the app access
# MAGIC The bundle passes the app's service principal automatically. If you run this by hand, find it with
# MAGIC `databricks apps get ai-impostor` (field `service_principal_client_id`).

# COMMAND ----------

if app_sp:
    spark.sql(f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{app_sp}`")
    spark.sql(f"GRANT USE SCHEMA ON SCHEMA {fq} TO `{app_sp}`")
    for table in ("games", "messages", "guesses"):
        # Least privilege: the app only appends rows; it never reads or creates tables.
        spark.sql(f"GRANT MODIFY ON TABLE {fq}.{table} TO `{app_sp}`")
    print(f"Granted {app_sp} insert access on {fq}.games/messages/guesses")
else:
    print("No app service principal given; skipping grants.")
