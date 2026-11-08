# Databricks notebook source
# MAGIC %md
# MAGIC # AI Impostor · 01 Game analytics
# MAGIC How good are people at spotting the AI, and which impostor personas fool them most?
# MAGIC This notebook builds dashboard-ready views in Unity Catalog (use them in an AI/BI dashboard or Genie space).

# COMMAND ----------

import re

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "ai_impostor")
catalog = dbutils.widgets.get("catalog").strip()
schema = dbutils.widgets.get("schema").strip()
for value in (catalog, schema):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Bad identifier: {value!r}")
fq = f"`{catalog}`.`{schema}`"

# COMMAND ----------

# MAGIC %md ## Headline: detection accuracy by who you were really talking to

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.v_detection_by_opponent AS
SELECT opponent_type,
       COUNT(*)                                   AS guesses,
       ROUND(AVG(CAST(correct AS INT)), 3)        AS accuracy,
       SUM(CASE WHEN guess = 'ai' THEN 1 ELSE 0 END) AS said_ai,
       SUM(CASE WHEN guess = 'human' THEN 1 ELSE 0 END) AS said_human
FROM {fq}.guesses
GROUP BY opponent_type
""")
display(spark.table(f"{fq}.v_detection_by_opponent"))

# COMMAND ----------

# MAGIC %md ## Which persona is the best impostor? (fool rate = share of players who thought the AI was human)

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.v_persona_fool_rate AS
SELECT persona,
       COUNT(*)                                       AS guesses,
       ROUND(AVG(CASE WHEN guess = 'human' THEN 1.0 ELSE 0.0 END), 3) AS fool_rate
FROM {fq}.guesses
WHERE opponent_type = 'ai'
GROUP BY persona
ORDER BY fool_rate DESC
""")
display(spark.table(f"{fq}.v_persona_fool_rate"))

# COMMAND ----------

# MAGIC %md ## Do longer conversations help people decide?

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.v_accuracy_by_chat_length AS
SELECT CASE WHEN g.message_count < 6 THEN '0-5'
            WHEN g.message_count < 12 THEN '6-11'
            WHEN g.message_count < 20 THEN '12-19'
            ELSE '20+' END                       AS messages_bucket,
       COUNT(*)                                  AS guesses,
       ROUND(AVG(CAST(q.correct AS INT)), 3)     AS accuracy
FROM {fq}.guesses q JOIN {fq}.games g USING (game_id)
GROUP BY 1
ORDER BY MIN(g.message_count)
""")
display(spark.table(f"{fq}.v_accuracy_by_chat_length"))

# COMMAND ----------

# MAGIC %md ## How do AI and human messages differ? (the "tells")

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.v_message_style AS
SELECT sender_kind,
       COUNT(*)                                                       AS messages,
       ROUND(AVG(LENGTH(text)), 1)                                    AS avg_chars,
       ROUND(AVG(CASE WHEN text RLIKE '\\\\?' THEN 1.0 ELSE 0.0 END), 3) AS question_rate,
       ROUND(AVG(CASE WHEN text = LOWER(text) THEN 1.0 ELSE 0.0 END), 3) AS all_lowercase_rate,
       ROUND(AVG(CASE WHEN text RLIKE '[.!]$' THEN 1.0 ELSE 0.0 END), 3) AS ends_with_punct_rate
FROM {fq}.messages
GROUP BY sender_kind
""")
display(spark.table(f"{fq}.v_message_style"))

# COMMAND ----------

# MAGIC %md ## Player leaderboard (all time)

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.v_leaderboard AS
SELECT player_nickname,
       COUNT(*)                              AS games,
       SUM(points)                           AS points,
       ROUND(AVG(CAST(correct AS INT)), 3)   AS accuracy
FROM {fq}.guesses
GROUP BY player_nickname
ORDER BY points DESC
""")
display(spark.table(f"{fq}.v_leaderboard").limit(20))

# COMMAND ----------

# MAGIC %md ## Group chat: is the AI harder to catch in a crowd?
# MAGIC Fool rate = share of votes that called an AI "human". Compared with one-on-one rounds.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.v_crowd_vs_solo AS
SELECT 'one-on-one' AS mode,
       COUNT(*) AS judgments,
       ROUND(AVG(CASE WHEN guess = 'human' THEN 1.0 ELSE 0.0 END), 3) AS ai_fool_rate
FROM {fq}.guesses WHERE opponent_type = 'ai'
UNION ALL
SELECT 'group' AS mode,
       COUNT(*) AS judgments,
       ROUND(AVG(CASE WHEN vote = 'human' THEN 1.0 ELSE 0.0 END), 3) AS ai_fool_rate
FROM {fq}.room_votes WHERE target_kind = 'ai'
""")
display(spark.table(f"{fq}.v_crowd_vs_solo"))

# COMMAND ----------

# MAGIC %md ## Group chat: which personas survive the vote, and does talking more give the AI away?

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.v_room_persona_survival AS
SELECT s.persona,
       COUNT(*)                                                    AS ai_seats,
       SUM(s.votes)                                                AS votes_received,
       ROUND(1 - SUM(s.voted_ai) / NULLIF(SUM(s.votes), 0), 3)      AS survival_rate,
       ROUND(AVG(m.lines), 1)                                      AS avg_lines_per_room
FROM {fq}.room_seats s
LEFT JOIN (
  SELECT room_id, alias, COUNT(*) AS lines FROM {fq}.room_messages GROUP BY room_id, alias
) m ON s.room_id = m.room_id AND s.alias = m.alias
WHERE s.sender_kind = 'ai'
GROUP BY s.persona
ORDER BY survival_rate DESC
""")
display(spark.table(f"{fq}.v_room_persona_survival"))

spark.sql(f"""
CREATE OR REPLACE VIEW {fq}.v_room_talkativeness AS
SELECT s.sender_kind,
       CASE WHEN COALESCE(m.lines, 0) <= 2 THEN '0-2 lines'
            WHEN m.lines <= 6 THEN '3-6 lines'
            ELSE '7+ lines' END                                      AS talkativeness,
       COUNT(*)                                                     AS seats,
       ROUND(SUM(s.voted_ai) / NULLIF(SUM(s.votes), 0), 3)          AS share_voted_ai
FROM {fq}.room_seats s
LEFT JOIN (
  SELECT room_id, alias, COUNT(*) AS lines FROM {fq}.room_messages GROUP BY room_id, alias
) m ON s.room_id = m.room_id AND s.alias = m.alias
GROUP BY 1, 2
ORDER BY 1, 2
""")
display(spark.table(f"{fq}.v_room_talkativeness"))
