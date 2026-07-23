# syntax=docker/dockerfile:1

# --- Stage 1: build the SpotiFLAC Go engine (vendored in spotiflac-go/) ---
# CGO is off, so this yields a fully static binary — taglib runs via wazero
# (pure-Go WASM), no C toolchain or shared libs needed at build or runtime.
FROM golang:1.26-bookworm AS engine
WORKDIR /build
COPY spotiflac-go/go.mod spotiflac-go/go.sum ./
RUN go mod download
COPY spotiflac-go/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" \
    -o /out/spotiflac-dl ./cmd/spotiflac-dl

# --- Stage 2: the FastAPI backend + ffmpeg + the static engine binary ---
# The engine is static, so slim is fine (no need for the old full image that
# hosted the pip package's native libs). ffmpeg is invoked at runtime by the
# engine for muxing/resample.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Drop the engine binary onto PATH; the adapter resolves it via shutil.which.
COPY --from=engine /out/spotiflac-dl /usr/local/bin/spotiflac-dl

COPY app ./app

ENV DATA_DIR=/data
# The engine treats this as its $HOME. Since SpotiFLAC v7.2.0 the community
# endpoints need a session file the desktop app creates after a one-time
# captcha; place it (from the host) at data/engine-home/.spotiflac/community_session.json
# — see "Community verification" in the README.
ENV SPOTIFLAC_ENGINE_HOME=/data/engine-home
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
