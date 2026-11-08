FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Jakarta \
    DB_PATH=/data/videotron.db

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 lamia \
    && useradd --uid 10001 --gid lamia --create-home lamia \
    && mkdir -p /data /app/uploads \
    && chown -R lamia:lamia /data /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy only application files; never include .env, local databases, or uploads.
COPY --chown=lamia:lamia app.py admin_sessions.py services.py media.py invoices.py email_templates.py notifications.py scheduler.py ./
COPY --chown=lamia:lamia static/ ./static/
COPY --chown=lamia:lamia icon/ ./icon/

USER lamia

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/screens', timeout=3); assert r.status == 200"]

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
