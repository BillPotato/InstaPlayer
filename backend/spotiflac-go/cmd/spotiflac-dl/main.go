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
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
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
const version = "Go engine (upstream 3f755f5)"

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

	if *maxRetries >= 0 {
		backend.SetCommunityRateLimitMaxRetries(*maxRetries)
	}

	if err := os.MkdirAll(*out, 0o755); err != nil {
		fatal("failed to create output dir: %v", err)
	}

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

		if err := downloadOne(t, *out, *quality, *qobuzToken, svcOrder, *allowFallback, *embedLyrics, *separator); err != nil {
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
// into the FLAC, which is the contract ingest depends on.
func downloadOne(t trackInfo, outDir, quality, qobuzToken string, services []string, allowFallback, embedLyrics bool, separator string) error {
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
				isrc, outDir, q, filenameFormat, false, t.TrackNumber,
				t.Name, t.Artists, t.AlbumName, t.AlbumArtist, t.ReleaseDate, false,
				t.CoverURL, false, t.TrackNumber, t.DiscNumber, t.TotalTracks, t.TotalDiscs,
				t.Copyright, t.Publisher, "", separator, spotifyURL, allowFallback, false, false, false)

		case "tidal":
			d := backend.NewTidalDownloader("")
			filename, err = d.Download(
				t.SpotifyID, outDir, q, filenameFormat, false, t.TrackNumber,
				t.Name, t.Artists, t.AlbumName, t.AlbumArtist, t.ReleaseDate, false,
				t.CoverURL, false, t.TrackNumber, t.DiscNumber, t.TotalTracks, t.TotalDiscs,
				t.Copyright, t.Publisher, "", separator, "", spotifyURL, allowFallback, false, false, false)

		case "amazon":
			d := backend.NewAmazonDownloader()
			filename, err = d.DownloadBySpotifyID(
				t.SpotifyID, outDir, q, filenameFormat, "", "", false, t.TrackNumber,
				t.Name, t.Artists, t.AlbumName, t.AlbumArtist, t.ReleaseDate, t.CoverURL,
				t.TrackNumber, t.DiscNumber, t.TotalTracks, false, t.TotalDiscs,
				t.Copyright, t.Publisher, "", separator, "", spotifyURL, false, false, false)

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

		fmt.Printf("  saved via %s: %s\n", svc, filepath.Base(filename))
		return nil
	}

	if lastErr == nil {
		lastErr = errors.New("no services attempted")
	}
	return lastErr
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
