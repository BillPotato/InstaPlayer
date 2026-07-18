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

# --- Local patches (re-applied on every vendor; see VENDORING.md) ------------
# Make the community retry budget configurable: upstream declares it as a const,
# so rewrite it to a var and add a setter — spotiflac-dl --max-retries (surfaced
# as TRACK_MAX_RETRIES in the FastAPI backend) needs to set it at runtime.
echo "Re-applying local patches (configurable retry budget) ..."
ENDPOINTS="$DEST/backend/community_endpoints.go"
if grep -q '^const communityRateLimitMaxRetries' "$ENDPOINTS"; then
  sed 's/^const communityRateLimitMaxRetries/var communityRateLimitMaxRetries/' \
    "$ENDPOINTS" > "$ENDPOINTS.tmp" && mv "$ENDPOINTS.tmp" "$ENDPOINTS"
fi
cat > "$DEST/backend/community_retries_patch.go" <<'EOF'
package backend

// LOCAL PATCH (not from upstream) — recreated by scripts/update-spotiflac.sh.
// Upstream declares communityRateLimitMaxRetries as a const; the script rewrites
// it to a var (in community_endpoints.go) and adds this setter so the retry
// budget is configurable via spotiflac-dl --max-retries.

// SetCommunityRateLimitMaxRetries overrides how many times a community-endpoint
// request retries on transient errors before giving up (values < 0 clamp to 0).
func SetCommunityRateLimitMaxRetries(n int) {
	if n < 0 {
		n = 0
	}
	communityRateLimitMaxRetries = n
}
EOF

echo "Tidying module (drops Wails) ..."
( cd "$DEST" && go mod tidy )

echo "Verifying static build ..."
( cd "$DEST" && CGO_ENABLED=0 go build -o /dev/null ./cmd/spotiflac-dl )

echo
echo "Done. Now update backend/spotiflac-go/VENDORING.md's upstream commit to: $COMMIT"
echo "Then rebuild the backend image to ship it."
