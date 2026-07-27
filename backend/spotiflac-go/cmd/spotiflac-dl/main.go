// Command spotiflac-dl is a headless CLI around the vendored SpotiFLAC `backend`
// package. The FastAPI backend invokes it as a subprocess (replacing the lagging
// `SpotiFLAC` pip package): it expands a Spotify track/album/playlist/artist URL
// into its tracks, then downloads each one as a title-tagged FLAC into --out,
// trying the requested services in priority order with fallback.
//
// The download/tag orchestration mirrors the upstream desktop app's
// App.DownloadTrack (app.go), minus the Wails GUI, queue/history DB bookkeeping,
// and settings plumbing — none of which apply to a one-shot headless run.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/afkarxyz/SpotiFLAC/backend"
)

// version is reported by --version and surfaced on the FastAPI
// /downloader/status card (rendered there as "SpotiFLAC <version>", so this
// string deliberately omits the "SpotiFLAC" prefix). The upstream commit lets
// that card show which engine build is running; keep it in sync with
// VENDORING.md when re-vendoring.
const version = "Go engine (upstream v7.2.0 / 02cfd11)"

// upstreamAppVersion identifies us as the SpotiFLAC release we vendored. The
// community endpoints sign requests with the app version (X-Sig-App-Version),
// so it must match a version the community server accepts. Keep in sync with
// the vendored release in VENDORING.md.
const upstreamAppVersion = "7.2.0"

// filenameFormat "title-artist" is the upstream default: no `{` tokens, so the
// downloaders emit "<Title> - <Artist>.flac". The embedded TITLE tag (always set
// by the providers' EmbedMetadata) is what ingest keys off; the name is cosmetic.
const filenameFormat = "title-artist"

// trackInfo is the subset of Spotify metadata the downloaders need, normalized
// from either TrackMetadata (single track) or AlbumTrackMetadata (album/playlist/
// artist track lists), which share most fields.
type trackInfo struct {
	SpotifyID   string
	Name        string
	Artists     string
	AlbumName   string
	AlbumArtist string
	ReleaseDate string
	CoverURL    string
	TrackNumber int
	DiscNumber  int
	TotalTracks int
	TotalDiscs  int
	Copyright   string
	Publisher   string
	DurationSec int
}

func main() {
	var (
		url           = flag.String("url", "", "Spotify track/album/playlist/artist URL (required)")
		out           = flag.String("out", "", "output directory for downloaded FLACs (required)")
		services      = flag.String("services", "qobuz,tidal,amazon", "comma-separated service priority order")
		quality       = flag.String("quality", "LOSSLESS", "quality profile: LOSSLESS (16-bit) or HI_RES (24-bit)")
		qobuzToken    = flag.String("qobuz-token", "", "optional custom Qobuz API base URL (https://...)")
		allowFallback = flag.Bool("allow-fallback", true, "allow each provider to fall back to its community source")
		maxRetries    = flag.Int("max-retries", -1, "community-endpoint retries on transient errors (429/502/504); -1 keeps the engine default")
		embedLyrics   = flag.Bool("embed-lyrics", true, "fetch and embed synced lyrics when available")
		separator     = flag.String("separator", ", ", "multi-artist separator for tags")
		timeoutSec    = flag.Int("timeout", 300, "metadata expansion timeout, seconds")
		showVersion   = flag.Bool("version", false, "print version and exit")
	)
	flag.Parse()

	if *showVersion {
		fmt.Println(version)
		return
	}

	if strings.TrimSpace(*url) == "" || strings.TrimSpace(*out) == "" {
		fmt.Fprintln(os.Stderr, "error: --url and --out are required")
		flag.Usage()
		os.Exit(2)
	}

	backend.AppVersion = upstreamAppVersion  // used to sign community requests

	// Lets the engine get past the community-verification captcha on its own;
	// without a handler registered it fails with "browser integration is not
	// ready". See openVerificationURL.
	backend.SetCommunityVerificationHandlers(openVerificationURL, func() {})

	if *maxRetries >= 0 {
		backend.SetCommunityRateLimitMaxRetries(*maxRetries)
	}

	if err := os.MkdirAll(*out, 0o755); err != nil {
		fatal("failed to create output dir: %v", err)
	}

	// Stage each download in a hidden subdir and only move the finished FLAC into
	// --out once ALL post-processing (metadata, lyrics) is done. The backend
	// watches --out and freezes a file's size into its (append-only) manifest the
	// moment it appears fully tagged; if we post-process in place afterwards the
	// size changes and the device's size check fails. Publishing atomically means
	// the backend only ever sees a complete, immutable file. Its scanner ignores
	// dot-prefixed dirs, so staged files stay invisible until published.
	stageDir := filepath.Join(*out, ".staging")
	if err := os.MkdirAll(stageDir, 0o755); err != nil {
		fatal("failed to create staging dir: %v", err)
	}
	defer os.RemoveAll(stageDir)

	svcOrder := parseServices(*services)
	if len(svcOrder) == 0 {
		fatal("no valid services in --services=%q", *services)
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(*timeoutSec)*time.Second)
	defer cancel()

	tracks, err := expandTracks(ctx, *url, *separator)
	if err != nil {
		fatal("failed to fetch metadata: %v", err)
	}
	total := len(tracks)
	if total == 0 {
		fatal("no tracks found for %s", *url)
	}

	saved := 0
	for i, t := range tracks {
		// Progress line parsed by the FastAPI adapter (spotiflac_adapter.py).
		fmt.Printf("Track [%d/%d] %s — %s\n", i+1, total, t.Name, t.Artists)

		if err := downloadOne(t, stageDir, *out, *quality, *qobuzToken, svcOrder, *allowFallback, *embedLyrics, *separator); err != nil {
			fmt.Fprintf(os.Stderr, "  failed: %v\n", err)
			continue
		}
		saved++
	}

	fmt.Printf("Downloaded %d/%d tracks\n", saved, total)
	if saved == 0 {
		fatal("all %d track(s) failed to download", total)
	}
}

// verifyCommandTimeout caps the solver subprocess. The engine gives the whole
// verification 5 minutes (communityVerifyTimeout); stop a little short of that
// so a wedged solver is reported as such rather than as a bare timeout.
const verifyCommandTimeout = 4 * time.Minute

// verifyCommand reads the solver invocation from SPOTIFLAC_VERIFY_CMD.
//
// Either a JSON argv array — what the FastAPI backend sets, so an interpreter
// path with spaces survives — or a plain command line split on whitespace, for
// an admin setting it by hand. Empty or "off" disables auto-verification.
func verifyCommand() []string {
	raw := strings.TrimSpace(os.Getenv("SPOTIFLAC_VERIFY_CMD"))
	if raw == "" || strings.EqualFold(raw, "off") {
		return nil
	}
	if strings.HasPrefix(raw, "[") {
		var argv []string
		if err := json.Unmarshal([]byte(raw), &argv); err != nil || len(argv) == 0 {
			fmt.Fprintf(os.Stderr, "  verification: ignoring malformed SPOTIFLAC_VERIFY_CMD\n")
			return nil
		}
		return argv
	}
	return strings.Fields(raw)
}

// openVerificationURL stands in for the desktop app's "open a browser window"
// handler (backend.SetCommunityVerificationHandlers).
//
// The community endpoints need a signed session, and minting one means passing
// a Cloudflare Turnstile challenge. The engine does everything around that
// itself: it bootstraps a challenge URL, starts a loopback callback server, and
// passes us the URL with the callback already attached as ?cb=. On the desktop
// a human clicks the checkbox and the page redirects to that callback; here we
// hand the URL to a solver command that drives a real browser instead. Either
// way the engine receives the grant on its own callback, exchanges it, and
// writes ~/.spotiflac/community_session.json — none of that is our business.
//
// So this only has to launch the solver. It runs in the background: the caller
// then blocks on its own 5-minute wait for the grant, which is the real
// deadline. With no command configured we print the URL, leaving the manual
// route (solve it elsewhere, copy the session file in) intact.
func openVerificationURL(challengeURL string) {
	fmt.Fprintf(os.Stderr, "  community verification required: %s\n", challengeURL)

	argv := verifyCommand()
	if len(argv) == 0 {
		fmt.Fprintln(os.Stderr, "  no solver configured (SPOTIFLAC_VERIFY_CMD unset) — "+
			"open the URL above in a browser to verify manually")
		return
	}

	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), verifyCommandTimeout)
		defer cancel()

		args := append(append([]string{}, argv[1:]...), challengeURL)
		cmd := exec.CommandContext(ctx, argv[0], args...)
		stdout, err := cmd.StdoutPipe()
		if err != nil {
			fmt.Fprintf(os.Stderr, "  verification solver failed to start: %v\n", err)
			return
		}
		cmd.Stderr = cmd.Stdout // same *os.File, so exec writes both to one fd

		fmt.Fprintf(os.Stderr, "  running verification solver: %s\n", argv[0])
		if err := cmd.Start(); err != nil {
			fmt.Fprintf(os.Stderr, "  verification solver failed to start: %v\n", err)
			return
		}
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			fmt.Fprintf(os.Stderr, "  [solver] %s\n", scanner.Text())
		}
		if err := cmd.Wait(); err != nil {
			fmt.Fprintf(os.Stderr, "  verification solver failed: %v\n", err)
			return
		}
		fmt.Fprintln(os.Stderr, "  verification solver finished")
	}()
}

// expandTracks turns a Spotify URL into its track list. GetFilteredSpotifyData
// returns one of a few concrete payload types depending on the URL kind.
func expandTracks(ctx context.Context, url, separator string) ([]trackInfo, error) {
	data, err := backend.GetFilteredSpotifyData(ctx, url, false, 0, separator, nil)
	if err != nil {
		return nil, err
	}

	switch v := data.(type) {
	case backend.TrackResponse:
		return []trackInfo{fromTrackMeta(v.Track)}, nil
	case *backend.TrackResponse:
		return []trackInfo{fromTrackMeta(v.Track)}, nil
	case backend.AlbumResponsePayload:
		return fromAlbumTracks(v.TrackList), nil
	case *backend.AlbumResponsePayload:
		return fromAlbumTracks(v.TrackList), nil
	case backend.PlaylistResponsePayload:
		return fromAlbumTracks(v.TrackList), nil
	case *backend.PlaylistResponsePayload:
		return fromAlbumTracks(v.TrackList), nil
	case backend.ArtistDiscographyPayload:
		return fromAlbumTracks(v.TrackList), nil
	case *backend.ArtistDiscographyPayload:
		return fromAlbumTracks(v.TrackList), nil
	default:
		return nil, fmt.Errorf("unsupported metadata payload type %T", data)
	}
}

func fromTrackMeta(m backend.TrackMetadata) trackInfo {
	return trackInfo{
		SpotifyID:   m.SpotifyID,
		Name:        m.Name,
		Artists:     m.Artists,
		AlbumName:   m.AlbumName,
		AlbumArtist: m.AlbumArtist,
		ReleaseDate: m.ReleaseDate,
		CoverURL:    m.Images,
		TrackNumber: m.TrackNumber,
		DiscNumber:  m.DiscNumber,
		TotalTracks: m.TotalTracks,
		TotalDiscs:  m.TotalDiscs,
		Copyright:   m.Copyright,
		Publisher:   m.Publisher,
		DurationSec: m.DurationMS / 1000,
	}
}

func fromAlbumTracks(list []backend.AlbumTrackMetadata) []trackInfo {
	out := make([]trackInfo, 0, len(list))
	for _, m := range list {
		// AlbumTrackMetadata carries no copyright/publisher; leave them empty.
		out = append(out, trackInfo{
			SpotifyID:   m.SpotifyID,
			Name:        m.Name,
			Artists:     m.Artists,
			AlbumName:   m.AlbumName,
			AlbumArtist: m.AlbumArtist,
			ReleaseDate: m.ReleaseDate,
			CoverURL:    m.Images,
			TrackNumber: m.TrackNumber,
			DiscNumber:  m.DiscNumber,
			TotalTracks: m.TotalTracks,
			TotalDiscs:  m.TotalDiscs,
			DurationSec: m.DurationMS / 1000,
		})
	}
	return out
}

// downloadOne tries each service in priority order and returns nil on the first
// success. Every provider path embeds full metadata (title/artist/album/cover)
// into the FLAC, which is the contract ingest depends on. Downloads land in
// stageDir; the finished file is moved into outDir (the job dir) only once all
// post-processing is done, so the backend never sees a mutating file.
func downloadOne(t trackInfo, stageDir, outDir, quality, qobuzToken string, services []string, allowFallback, embedLyrics bool, separator string) error {
	spotifyURL := ""
	if t.SpotifyID != "" {
		spotifyURL = "https://open.spotify.com/track/" + t.SpotifyID
	}

	var lastErr error
	for _, svc := range services {
		q := serviceQuality(svc, quality)
		var (
			filename string
			err      error
		)

		switch svc {
		case "qobuz":
			// Qobuz is keyed by ISRC, resolved from the Spotify ID via songlink.
			isrc := ""
			if t.SpotifyID != "" {
				isrc = backend.ResolveTrackISRC(t.SpotifyID)
			}
			if isrc == "" {
				lastErr = errors.New("qobuz: could not resolve ISRC")
				fmt.Fprintln(os.Stderr, "  qobuz skipped: no ISRC")
				continue
			}
			d := backend.NewQobuzDownloader()
			if strings.HasPrefix(strings.TrimSpace(qobuzToken), "https://") {
				d.SetCustomAPIURL(strings.TrimRight(strings.TrimSpace(qobuzToken), "/"))
			}
			filename, err = d.DownloadTrackWithISRC(
				isrc, stageDir, q, filenameFormat, false, t.TrackNumber,
				t.Name, t.Artists, t.AlbumName, t.AlbumArtist, t.ReleaseDate, false,
				t.CoverURL, false, t.TrackNumber, t.DiscNumber, t.TotalTracks, t.TotalDiscs,
				t.Copyright, t.Publisher, "", separator, spotifyURL, allowFallback, false, false, false)

		case "tidal":
			d := backend.NewTidalDownloader("")
			filename, err = d.Download(
				t.SpotifyID, stageDir, q, filenameFormat, false, t.TrackNumber,
				t.Name, t.Artists, t.AlbumName, t.AlbumArtist, t.ReleaseDate, false,
				t.CoverURL, false, t.TrackNumber, t.DiscNumber, t.TotalTracks, t.TotalDiscs,
				t.Copyright, t.Publisher, "", separator, "", spotifyURL, allowFallback,
				false, "", false, false, false)  // allowAtmosFallback, atmosFallbackQuality, useFirstArtistOnly, useSingleGenre, embedGenre

		case "amazon":
			d := backend.NewAmazonDownloader()
			filename, err = d.DownloadBySpotifyID(
				t.SpotifyID, stageDir, q, filenameFormat, "", "", false, t.TrackNumber,
				t.Name, t.Artists, t.AlbumName, t.AlbumArtist, t.ReleaseDate, t.CoverURL,
				t.TrackNumber, t.DiscNumber, t.TotalTracks, false, t.TotalDiscs,
				t.Copyright, t.Publisher, "", separator, "", spotifyURL, allowFallback,
				false, "", false, false, false)  // allowAtmosFallback, atmosFallbackQuality, useFirstArtistOnly, useSingleGenre, embedGenre

		default:
			lastErr = fmt.Errorf("unknown service %q", svc)
			continue
		}

		if err != nil {
			lastErr = fmt.Errorf("%s: %w", svc, err)
			fmt.Fprintf(os.Stderr, "  %s failed: %v\n", svc, err)
			continue
		}

		alreadyExists := strings.HasPrefix(filename, "EXISTS:")
		filename = strings.TrimPrefix(filename, "EXISTS:")

		if !alreadyExists {
			if _, verr := backend.ValidateDownloadedTrackDuration(filename, t.DurationSec); verr != nil {
				_ = os.Remove(filename)
				lastErr = fmt.Errorf("%s: validation failed: %w", svc, verr)
				fmt.Fprintf(os.Stderr, "  %s failed validation: %v\n", svc, verr)
				continue
			}
			if embedLyrics {
				embedTrackLyrics(filename, t)
			}
		}

		// Publish only now that the file is complete: atomically move it out of
		// staging into the job dir the backend watches.
		published, perr := publish(filename, outDir)
		if perr != nil {
			lastErr = fmt.Errorf("%s: publish failed: %w", svc, perr)
			fmt.Fprintf(os.Stderr, "  %s publish failed: %v\n", svc, perr)
			continue
		}
		fmt.Printf("  saved via %s: %s\n", svc, filepath.Base(published))
		return nil
	}

	if lastErr == nil {
		lastErr = errors.New("no services attempted")
	}
	return lastErr
}

// publish atomically moves a finished file out of staging into outDir (same
// filesystem → os.Rename is atomic). Returns the final path. Any stale file of
// the same name is removed first so the move can't fail on a duplicate title.
func publish(src, outDir string) (string, error) {
	dst := filepath.Join(outDir, filepath.Base(src))
	_ = os.Remove(dst)
	if err := os.Rename(src, dst); err != nil {
		return "", err
	}
	return dst, nil
}

// embedTrackLyrics best-effort fetches synced lyrics and writes them into the
// audio file. Failure is non-fatal — the track is already downloaded and tagged.
func embedTrackLyrics(filename string, t trackInfo) {
	if t.SpotifyID == "" {
		return
	}
	switch strings.ToLower(filepath.Ext(filename)) {
	case ".flac", ".mp3", ".m4a":
	default:
		return
	}

	client := backend.NewLyricsClient()
	resp, _, err := client.FetchLyricsAllSources(t.SpotifyID, t.Name, t.Artists, t.AlbumName, t.DurationSec)
	if err != nil || resp == nil || len(resp.Lines) == 0 {
		return
	}
	lrc := client.ConvertToLRC(resp, t.Name, t.Artists)
	if strings.TrimSpace(lrc) == "" {
		return
	}
	if err := backend.EmbedLyricsOnlyUniversal(filename, lrc); err != nil {
		fmt.Fprintf(os.Stderr, "  lyrics embed failed: %v\n", err)
	}
}

// serviceQuality maps our LOSSLESS/HI_RES profile onto each provider's own
// quality code (see the upstream frontend's useDownload.ts mapping).
func serviceQuality(service, quality string) string {
	hires := isHiRes(quality)
	switch service {
	case "qobuz":
		if hires {
			return "27" // 24-bit hi-res
		}
		return "6" // 16-bit lossless
	case "amazon":
		if hires {
			return "24"
		}
		return "16"
	case "tidal":
		if hires {
			return "HI_RES_LOSSLESS"
		}
		return "LOSSLESS"
	}
	return quality
}

func isHiRes(q string) bool {
	switch strings.ToUpper(strings.TrimSpace(q)) {
	case "HI_RES", "HI_RES_LOSSLESS", "HIRES", "HI-RES", "24", "27", "MAX", "MASTER":
		return true
	}
	return false
}

func parseServices(csv string) []string {
	seen := map[string]struct{}{}
	out := make([]string, 0, 3)
	for _, s := range strings.Split(csv, ",") {
		s = strings.ToLower(strings.TrimSpace(s))
		switch s {
		case "qobuz", "tidal", "amazon":
			if _, dup := seen[s]; !dup {
				seen[s] = struct{}{}
				out = append(out, s)
			}
		}
	}
	return out
}

func fatal(format string, args ...interface{}) {
	fmt.Fprintf(os.Stderr, "error: "+format+"\n", args...)
	os.Exit(1)
}
