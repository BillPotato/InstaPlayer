# SpotiFLAC targets CPython 3.11 and ships a native Go tagger; build on a full
# (non-slim) image so the bundled binary's shared libs are present.
FROM python:3.11-bullseye

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# ffmpeg is commonly needed by audio tooling for muxing/transcode fallbacks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY docker-entrypoint.sh /srv/docker-entrypoint.sh

ENV DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 8000

# The entrypoint upgrades SpotiFLAC to the latest release on start (see the
# script), then execs the CMD below. Invoked via `sh` so a missing +x bit on
# Windows checkouts doesn't matter.
ENTRYPOINT ["sh", "/srv/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
