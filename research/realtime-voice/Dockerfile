# ApexVoice V2 realtime voice stack, ARM64.
#
# Deliberately pinned to the architecture this was benchmarked on (Oracle Ampere
# A1). python:3.12-slim is used rather than 3.14 because audioop-lts and the
# onnxruntime wheels are most reliably available there, and 3.12 avoids the
# stdlib audioop removal entirely if the shim is absent.
FROM python:3.12-slim-bookworm

LABEL org.opencontainers.image.title="apex-voice-realtime" \
      org.opencontainers.image.description="Pipecat realtime voice prototype with local Piper TTS" \
      org.opencontainers.image.licenses="Proprietary"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APEX_VOICE_ENGINE=legacy \
    APEX_VOICE_ENABLED_ENGINES=legacy

# espeak-ng-data is required by Piper for phonemisation. Without it synthesis
# fails at runtime with a missing-data error that looks like a model problem.
RUN apt-get update && apt-get install -y --no-install-recommends \
        espeak-ng-data \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY apex_voice ./apex_voice
COPY research ./research
COPY benchmarks ./benchmarks
COPY tests ./tests

# Voices are mounted, not baked in: 120 MB of models does not belong in an image
# layer, and the licence of each voice must be reviewed before it ships.
VOLUME ["/voices", "/cache"]

# Non-root. The service needs no privileges and should never have any.
RUN useradd --create-home --uid 10001 apex \
    && mkdir -p /voices /cache \
    && chown -R apex:apex /app /voices /cache
USER apex

# Piper cold-loads in ~350-400 ms on 2 vCPU; allow a generous start period.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import apex_voice.audio as a; assert a.codec_ready()" || exit 1

CMD ["python", "-m", "apex_voice.serve"]
