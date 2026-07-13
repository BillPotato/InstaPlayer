package main

// Build spike: a blank import forces the entire upstream `backend` package —
// and all its transitive deps (taglib/wazero, mp4ff, go-flac, …) — to compile
// and link. If this builds with CGO_ENABLED=0, we get a static binary and a
// trivial Docker image. The real orchestrator replaces this file in Step 2.
import (
	_ "github.com/afkarxyz/SpotiFLAC/backend"
)

func main() {}
