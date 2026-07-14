#!/usr/bin/env bash
# Re-vendor the SpotiFLAC Go engine (backend/spotiflac-go/backend/) from an
# upstream checkout. This is the "keep current" story that replaced the old pip
# auto-upgrade: the engine is a vendored binary, so staying current means
# re-copying the upstream Go source and rebuilding the image.
#
# Usage:
#   scripts/update-spotiflac.sh [path-to-SpotiFLAC-checkout]
#
# With no argument it uses ../SpotiFLAC (next to this repo); if that's missing it
# shallow-clones upstream to a temp dir. Override the clone URL with
# SPOTIFLAC_UPSTREAM_URL.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO_ROOT/backend/spotiflac-go"
UPSTREAM_URL="${SPOTIFLAC_UPSTREAM_URL:-https://github.com/spotbye/SpotiFLAC.git}"

# GUI-only files that pull in Wails; the headless CLI doesn't use them, and
# dropping them is what lets the module build with CGO_ENABLED=0 and no Wails.
GUI_ONLY="file_dialog.go folder.go lyrics_reader.go"

SRC="${1:-$REPO_ROOT/../SpotiFLAC}"
CLONED=""
if [ ! -d "$SRC/backend" ]; then
  echo "No SpotiFLAC checkout at '$SRC'; shallow-cloning $UPSTREAM_URL ..."
  SRC="$(mktemp -d)"
  CLONED="$SRC"
  git clone --depth 1 "$UPSTREAM_URL" "$SRC"
fi
trap '[ -n "$CLONED" ] && rm -rf "$CLONED"' EXIT

COMMIT="$(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "Vendoring backend/ from '$SRC' (commit $COMMIT) ..."

rm -rf "$DEST/backend"
mkdir -p "$DEST/backend"
cp "$SRC"/backend/*.go "$DEST/backend/"
cp "$SRC/go.mod" "$SRC/go.sum" "$DEST/"

for f in $GUI_ONLY; do
  rm -f "$DEST/backend/$f"
done

echo "Tidying module (drops Wails) ..."
( cd "$DEST" && go mod tidy )

echo "Verifying static build ..."
( cd "$DEST" && CGO_ENABLED=0 go build -o /dev/null ./cmd/spotiflac-dl )

echo
echo "Done. Now update backend/spotiflac-go/VENDORING.md's upstream commit to: $COMMIT"
echo "Then rebuild the backend image to ship it."
