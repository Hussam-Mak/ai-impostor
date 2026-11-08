# Public game server for AI Impostor, run as a Hugging Face Docker Space.
# It builds straight from the public GitHub repo, so the Space holds only this
# file and README.md. Databricks credentials come from the Space's secrets.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user
ENV PATH=/home/user/.local/bin:$PATH

# Changes whenever main gets a new commit, which forces a fresh clone on rebuild.
ADD --chown=user https://api.github.com/repos/Hussam-Mak/ai-impostor/commits/main /home/user/version.json
RUN git clone --depth 1 https://github.com/Hussam-Mak/ai-impostor.git src \
 && pip install --no-cache-dir --user -r src/app/requirements.txt

ENV HOST=0.0.0.0 \
    PORT=7860 \
    IMPOSTOR_LOCAL_DATA_DIR=/tmp/impostor \
    IMPOSTOR_ALLOWED_ORIGINS=https://hussam-mak.github.io \
    IMPOSTOR_PROXY_HOPS=1

EXPOSE 7860
CMD ["python", "src/app/main.py"]
