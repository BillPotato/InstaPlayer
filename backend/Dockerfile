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

# --- Optional: the Turnstile solver (turnstile_solver/) ---
# Off by default. The server never imports the solver, and chromium + xvfb
# add several hundred MB, so you only pay for them if you ask. Set it in
# backend/.env — compose reads that when interpolating build args, so it
# survives every rebuild:
#
#     echo "WITH_SOLVER=1" >> .env && docker compose build
#
# (--build-arg on the command line works too, but applies to that one build
# only; the next plain rebuild quietly drops the browser again.)
#
# With it on, the container can run the community-verification captcha itself
# (`docker compose exec backend python -m turnstile_solver <url>`) instead of
# you copying in a session file produced by the desktop app. Xvfb is what
# makes that work headlessly — the solver starts it on demand, and a real
# browser on a virtual screen passes Turnstile far more often than Chrome's
# headless mode does.
# (nodriver itself is in requirements.txt; this arg is only about the browser.)
#
# Google Chrome rather than Debian's chromium, where one is available.
# Turnstile scores the client, and a chromium build on a datacentre address is
# an unusual enough fingerprint to be treated as suspicious on its own — the
# solver could tick Cloudflare's *test* checkbox in this image while a real
# sitekey silently withheld its token. Chrome is what the overwhelming
# majority of real visitors run. Google only ships amd64 debs, so other
# architectures keep chromium.
ARG WITH_SOLVER=0
RUN if [ "$WITH_SOLVER" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends xvfb tzdata \
            fonts-liberation fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji \
        && if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
               apt-get install -y --no-install-recommends wget gnupg \
               && wget -qO- https://dl.google.com/linux/linux_signing_key.pub \
                   | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
               && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
                   > /etc/apt/sources.list.d/google-chrome.list \
               && apt-get update \
               && apt-get install -y --no-install-recommends google-chrome-stable; \
           else \
               apt-get install -y --no-install-recommends chromium; \
           fi \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# Pure Python and tiny, so it goes in either way — without WITH_SOLVER it
# simply has no browser to drive. Chrome lands at /usr/bin/google-chrome-stable
# (chromium at /usr/bin/chromium on non-amd64), which
# the solver finds on its own; no CHROME_PATH needed.
COPY turnstile_solver ./turnstile_solver
# Keep Cloudflare's clearance cookie on the data volume so a solved challenge
# survives a container restart.
ENV TS_PROFILE_DIR=/data/chrome-profile

# A container defaults to UTC while its traffic leaves from wherever the host
# is. Anti-bot scoring compares the browser's timezone against the address the
# request came from, and a mismatch counts against you — so set TZ in
# backend/.env to the host's zone (e.g. TZ=Asia/Bangkok); compose passes that
# file through env_file, so it reaches the browser without a rebuild. Only the
# offset really matters. Unset leaves UTC, which is right for a UTC host.

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
