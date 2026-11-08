"""Entry point for Databricks Apps (and local runs): python main.py"""

import logging
import os

import uvicorn

from impostor.api import create_app

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = create_app()

if __name__ == "__main__":
    # Databricks Apps sets DATABRICKS_APP_PORT; one worker because game state is in memory.
    on_databricks = bool(os.getenv("DATABRICKS_APP_PORT"))
    port = int(os.getenv("DATABRICKS_APP_PORT", os.getenv("PORT", "8000")))
    host = os.getenv("HOST", "0.0.0.0" if on_databricks else "127.0.0.1")
    uvicorn.run(app, host=host, port=port, workers=1)
