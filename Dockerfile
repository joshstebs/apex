FROM python:3.12-slim

# Call state must survive a container restart. Without a mounted volume at
# DB_PATH, SQLite data disappears on redeploy, and MTProto-less setups silently
# lose every stored message.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/voice_agents.db \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Writable state directory for the SQLite fallback and local TTS clips.
RUN mkdir -p /data && useradd --create-home --uid 10001 apex \
    && chown -R apex:apex /app /data
USER apex

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
