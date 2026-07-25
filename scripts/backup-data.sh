#!/usr/bin/env bash
# Back up the backend's persistent state (backend/data/) to a timestamped
# tarball. Excludes the transient per-job download dirs (data/jobs/) — those
# are disposable by design (the reaper deletes them anyway).
#
# What this preserves: the SQLite job DB, per-day logs, probe cache + health
# history, admin state (banner/probe switch), and the engine home with the
# community session file (data/engine-home/.spotiflac/community_session.json).
#
# Usage:
#   ./scripts/backup-data.sh [backup-dir]     # default: ./backups
#
# Cron example (daily at 04:00, keep the default 14):
#   0 4 * * * cd /path/to/InstaPlayer && ./scripts/backup-data.sh >> backups/backup.log 2>&1
#
# Note: the SQLite DB only holds transient job statuses, so a live copy is
# acceptable; for a guaranteed-consistent snapshot run this while no import is
# active (check the dashboard).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$REPO_ROOT/backend/data"
BACKUP_DIR="${1:-$REPO_ROOT/backups}"
KEEP="${KEEP:-14}"   # how many backups to retain (override: KEEP=30 ./scripts/backup-data.sh)

if [[ ! -d "$DATA_DIR" ]]; then
  echo "No data directory at $DATA_DIR — nothing to back up." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/instaplayer-data-$STAMP.tar.gz"

tar -czf "$OUT" \
  -C "$REPO_ROOT/backend" \
  --exclude='data/jobs' \
  --exclude='data/probe-*' \
  data

echo "Wrote $OUT ($(du -h "$OUT" | cut -f1))"

# Retention: keep the newest $KEEP, drop the rest.
mapfile -t OLD < <(ls -1t "$BACKUP_DIR"/instaplayer-data-*.tar.gz 2>/dev/null | tail -n "+$((KEEP + 1))")
for f in "${OLD[@]:-}"; do
  [[ -n "$f" ]] || continue
  rm -f -- "$f"
  echo "Pruned $f"
done
