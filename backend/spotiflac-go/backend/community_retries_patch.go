package backend

// LOCAL PATCH (not from upstream) — re-applied after each vendoring by
// scripts/update-spotiflac.sh; see backend/spotiflac-go/VENDORING.md.
//
// Upstream declares `communityRateLimitMaxRetries` as a plain const. Our
// update script rewrites it to a `var` (in community_endpoints.go) and adds
// this setter so the retry budget can be configured at runtime via the
// spotiflac-dl `--max-retries` flag (surfaced as TRACK_MAX_RETRIES in the
// FastAPI backend).

// SetCommunityRateLimitMaxRetries overrides how many times a community-endpoint
// request retries on transient errors (429/502/504) before giving up. Values
// below 0 are clamped to 0 (a single attempt, no retries).
func SetCommunityRateLimitMaxRetries(n int) {
	if n < 0 {
		n = 0
	}
	communityRateLimitMaxRetries = n
}
