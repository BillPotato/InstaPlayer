#!/bin/sh
# Pull the newest SpotiFLAC on every container start. A fresh process is the
# ONLY way an upgrade takes effect — a running server keeps using the module
# it already imported, so upgrading here (before uvicorn starts) is what makes
# "always newest" actually work. Redeploy/restart to pick up new releases.
#
# Best-effort: if PyPI is slow or down, fall back to the version baked into the
# image so the server always boots. Set SPOTIFLAC_AUTO_UPGRADE=0 to disable
# (e.g. for a reproducible build).
set -e

if [ "${SPOTIFLAC_AUTO_UPGRADE:-1}" != "0" ]; then
  echo "[entrypoint] Upgrading SpotiFLAC to the latest release..."
  if pip install --upgrade --no-cache-dir SpotiFLAC; then
    echo "[entrypoint] SpotiFLAC is up to date."
  else
    echo "[entrypoint] WARNING: SpotiFLAC upgrade failed; using the baked-in version."
  fi
fi

exec "$@"
