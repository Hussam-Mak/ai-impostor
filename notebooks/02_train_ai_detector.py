# Databricks notebook source
# MAGIC %md
# MAGIC # AI Impostor · 02 Train an AI-message detector
# MAGIC Can a model spot the impostor better than people can? We train a text classifier on every chat
# MAGIC message (label: written by the AI or by a human), track it with MLflow, register it in Unity Catalog,
# MAGIC then compare its per-conversation verdicts against the players' guesses.

# COMMAND ----------

# MAGIC %pip install -q scikit-learn mlflow
# MAGIC %restart_python

# COMMAND ----------

import re

import mlflow
import numpy as np
import pandas as pd
from mlflow.models import infer_signature
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("schema", "ai_impostor")
catalog = dbutils.widgets.get("catalog").strip()
schema = dbutils.widgets.get("schema").strip()
for value in (catalog, schema):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Bad identifier: {value!r}")
fq = f"`{catalog}`.`{schema}`"
MODEL_NAME = f"{catalog}.{schema}.ai_message_detector"
MIN_PER_CLASS = 20

# COMMAND ----------

messages = spark.table(f"{fq}.messages").select("game_id", "seq", "sender_kind", "sender_nickname", "text").toPandas()
messages["label"] = (messages["sender_kind"] == "ai").astype(int)
counts = messages["label"].value_counts().to_dict()
print(f"Messages: {len(messages)} · AI: {counts.get(1, 0)} · human: {counts.get(0, 0)}")

if min(counts.get(0, 0), counts.get(1, 0)) < MIN_PER_CLASS or messages["game_id"].nunique() < 5:
    dbutils.notebook.exit(f"Not enough games yet (need {MIN_PER_CLASS}+ messages of each kind). Play more and re-run.")

# COMMAND ----------

# Split by game so messages from one chat never land in both train and test.
splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
train_idx, test_idx = next(splitter.split(messages, messages["label"], groups=messages["game_id"]))
train, test = messages.iloc[train_idx], messages.iloc[test_idx]

def text_column(frame):
    """Serving sends a DataFrame with a `text` column; the vectorizers need the strings."""
    return frame["text"].astype(str)


# The model takes a DataFrame with a `text` column, so it works the same in MLflow serving.
pipeline = Pipeline([
    ("text", FunctionTransformer(text_column)),
    ("features", FeatureUnion([
        ("words", TfidfVectorizer(ngram_range=(1, 2), min_df=1, lowercase=False)),
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2, lowercase=False)),
    ])),
    ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
])

mlflow.set_registry_uri("databricks-uc")
with mlflow.start_run(run_name="ai_message_detector") as run:
    pipeline.fit(train[["text"]], train["label"])
    proba = pipeline.predict_proba(test[["text"]])[:, 1]
    message_accuracy = accuracy_score(test["label"], proba >= 0.5)
    message_auc = roc_auc_score(test["label"], proba) if test["label"].nunique() == 2 else float("nan")
    mlflow.log_params({"train_messages": len(train), "test_messages": len(test), "model": "tfidf_word+char_logreg"})
    mlflow.log_metrics({"message_accuracy": message_accuracy, "message_auc": message_auc})

    sample = train[["text"]].head(5)
    # pyfunc serving calls predict(): 1 = written by the AI, 0 = written by a human.
    signature = infer_signature(sample, pipeline.predict(sample))
    mlflow.sklearn.log_model(
        pipeline, artifact_path="model", signature=signature, input_example=sample,
        registered_model_name=MODEL_NAME,
    )
    print(f"Per-message accuracy {message_accuracy:.3f}, AUC {message_auc:.3f} · run {run.info.run_id}")

# COMMAND ----------

# MAGIC %md ## Model vs. players: who spots the impostor better?
# MAGIC For each held-out game, the model reads only the stranger's messages and says AI if their average
# MAGIC AI-probability is above 0.5. We compare with what the players guessed in those same games.

# COMMAND ----------

test = test.assign(p_ai=proba)
guesses = spark.table(f"{fq}.guesses").select("game_id", "player_nickname", "opponent_type", "correct").toPandas()
guesses = guesses[guesses["game_id"].isin(test["game_id"].unique())]

rows = []
for g in guesses.itertuples():
    chat = test[test["game_id"] == g.game_id]
    # The stranger is whoever is not this player.
    stranger = chat[(chat["sender_kind"] == "ai") | (chat["sender_nickname"] != g.player_nickname)]
    if stranger.empty:
        continue
    model_says_ai = stranger["p_ai"].mean() >= 0.5
    rows.append({
        "game_id": g.game_id,
        "truth": g.opponent_type,
        "player_correct": bool(g.correct),
        "model_correct": model_says_ai == (g.opponent_type == "ai"),
    })

comparison = pd.DataFrame(rows)
if comparison.empty:
    dbutils.notebook.exit("No held-out games with guesses yet.")

summary = comparison.groupby("truth")[["player_correct", "model_correct"]].mean().round(3)
summary.loc["overall"] = comparison[["player_correct", "model_correct"]].mean().round(3)
display(summary.reset_index())

with mlflow.start_run(run_id=run.info.run_id):
    mlflow.log_metrics({
        "game_model_accuracy": float(comparison["model_correct"].mean()),
        "game_player_accuracy": float(comparison["player_correct"].mean()),
    })

# COMMAND ----------

# MAGIC %md ## The biggest "AI tells" the model learned

# COMMAND ----------

words = pipeline.named_steps["features"].transformer_list[0][1]
n_words = len(words.vocabulary_)
coef = pipeline.named_steps["clf"].coef_[0][:n_words]
vocab = np.array(words.get_feature_names_out())
order = np.argsort(coef)
display(pd.DataFrame({
    "most_ai_like": vocab[order[::-1][:15]],
    "most_human_like": vocab[order[:15]],
}))
