# Android Deployment Plan — InstaPlayer → Google Play

Step-by-step plan for shipping the Expo app in `app/` to the Play Store. Written for this
repo's setup: Expo SDK 56, CNG (generated `android/` is gitignored), local JDK 17 + Android
SDK on Windows, package id `com.instaplayer.app`.

---

## Phase 0 — Decisions to lock in first

| Decision | Recommendation | Why it matters |
|---|---|---|
| **Application ID** | Keep `com.instaplayer.app` or switch to a domain you control (`com.yourdomain.instaplayer`) | **Cannot ever change after the first Play upload.** Decide now in `app.json → android.package`. |
| **Build path** | **EAS Build (cloud) for release AABs**; keep local Gradle for dev | Windows can't run `eas build --local`, and local release signing fights CNG (prebuild regenerates `android/`, wiping signing config). EAS generates + stores the upload keystore, auto-increments versionCode, and outputs a ready AAB. Free tier is enough for this app's cadence. |
| **Signing** | Play App Signing (default) + EAS-managed upload key | Google keeps the app signing key; the upload key lives in your Expo account. Nothing to lose on this PC. |

The fully-local release path is documented in the appendix if you'd rather avoid an Expo
account.

## Phase 1 — One-time accounts & assets

1. **Google Play Console developer account** — one-time $25, identity verification takes a
   few days. A *personal* account also imposes a closed-testing requirement before
   production (see Phase 5).
2. **Privacy policy URL** (required even though the app collects nothing). One static page:
   "InstaPlayer stores music, playlists, history and settings only on your device; the only
   network traffic is to the server address you configure." GitHub Pages is fine.
3. **Replace the template artwork** — the repo still ships Expo's default icons/splash:
   - `assets/images/icon.png` (1024×1024), `android-icon-foreground/background/monochrome.png`
     (adaptive icon layers), `splash-icon.png`.
   - Delete unused template images (`react-logo*`, `expo-badge*`, `tabIcons/`, etc.).
   - Play listing also needs: 512×512 icon, 1024×500 feature graphic, ≥2 phone screenshots
     (take them in the app — dark theme, library + player look best).
4. **Expo account** for EAS: `npx eas-cli login` (create account at expo.dev if needed).

## Phase 2 — App config for release (`app/app.json`)

- [ ] `android.package` — final application ID (Phase 0).
- [ ] `version: "1.0.0"` and add `android.versionCode: 1` (EAS can auto-increment with
      `"autoIncrement": true` in the build profile — recommended).
- [ ] Icons/splash paths point at the new artwork.
- [ ] Sanity-check permissions after a prebuild: the merged manifest should contain only
      `INTERNET`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MEDIA_PLAYBACK`,
      `POST_NOTIFICATIONS`, `WAKE_LOCK` (+ storage-free SAF pickers add none). No location,
      no contacts, nothing else.
- [ ] Keep `usesCleartextTraffic: true` (needed for LAN/VPN servers) — allowed by Play; the
      About screen already recommends VPN/TLS.

## Phase 3 — EAS setup (one time)

```powershell
cd app
npx eas-cli build:configure   # creates eas.json, links the project
```

Suggested `eas.json`:

```json
{
  "build": {
    "production": {
      "android": { "buildType": "app-bundle", "autoIncrement": true }
    },
    "preview": {
      "android": { "buildType": "apk" }
    }
  }
}
```

- `production` → AAB for Play.
- `preview` → installable APK for sideload-testing release-mode behavior on your own phone.

First `eas build` asks to generate an Android keystore — say yes (EAS stores it; you can
`eas credentials` to download a backup — do that once and keep it somewhere safe).

## Phase 4 — Build & verify a release candidate

1. `eas build -p android --profile preview` → download APK → install on a real phone
   (`adb install app.apk`).
2. **Release-mode test pass** (release builds behave differently from dev — no Metro):
   - [ ] Fresh install: setup screen → Skip → empty library states look right.
   - [ ] Connect to server, import a playlist end-to-end; kill-test mid-import (saved tracks survive).
   - [ ] Local import: files + folder pickers, tags/art correct.
   - [ ] Playback: background + screen off for 10+ min, notification controls, lock screen art.
   - [ ] Airplane mode: everything except import/server settings works offline.
   - [ ] Shuffle/repeat/speed/sleep timer/lyrics/queue reorder.
   - [ ] Theme light/dark/system + accents.
   - [ ] Storage screen delete reclaims space; deleting the playing song advances safely.
3. Fix → rebuild → repeat until clean.
4. `eas build -p android --profile production` → AAB for upload.

## Phase 5 — Play Console setup & first release

1. **Create app** in Play Console: name *InstaPlayer*, category *Music & Audio*, free, no ads.
2. **Store listing**: description must not mention any third-party music service — position
   it as an *offline player for your own self-hosted music server* (same category as
   Subsonic/Jellyfin clients). Upload icon, feature graphic, screenshots.
3. **App content declarations** (left sidebar — all required):
   - Privacy policy URL.
   - Data safety: **no data collected, no data shared** (server traffic is user-configured,
     data never reaches the developer).
   - **Foreground service**: declare type `mediaPlayback`, purpose: continuous music
     playback with user-visible controls. Provide a short screen-recording link (record the
     app playing with the notification visible).
   - Content rating questionnaire (music player → Everyone).
   - Target audience: 13+ (avoid the children-policy overhead).
   - Ads: none. News app: no. COVID app: no.
4. **Upload the AAB** to the **Internal testing** track first — installable by you within
   minutes via an opt-in link. Re-verify on a real device.
5. **Personal-account gate**: personal developer accounts created after Nov 2023 must run a
   **closed test with a minimum number of opted-in testers continuously for 14 days**
   (originally 20 testers; Google has adjusted the number — the Play Console dashboard shows
   your exact requirement) before you can apply for production access. Recruit friends /
   r/androidapps testers early; the 14-day clock only counts days with enough testers.
6. After production access: promote the build to **Production**, use a staged rollout
   (20% → 100%) if you like. First review typically takes a few days.

## Phase 6 — Updates (every release after the first)

1. Bump `version` in `app.json` (versionCode auto-increments via EAS).
2. `eas build -p android --profile production` → upload AAB to a track → promote.
3. Keep the target API level current: Google requires new/updated apps to target an API
   level within one year of the latest Android release (deadline each Aug 31) — in practice,
   upgrade the Expo SDK about once a year. Watch for the expo-audio release that adds
   playlist lock-screen support (expo/expo#46020) — swapping it in restores native gapless +
   notification next/prev buttons (see `app/README.md` → Key design decisions).

## Risks / gotchas specific to this app

- **Reviewer experience**: a reviewer has no server. That's fine — setup has "Skip for now",
  the app opens to a working (empty) library, and local device import works without any
  server. Mention in the review notes: "Music player for self-hosted servers; all features
  except server import work without one. Local file import can be tested with any audio file."
- **Foreground service declaration video** is the most commonly-missed item — prepare it
  before submitting.
- **Keystore discipline**: with EAS + Play App Signing there's nothing critical on this PC,
  but still run `eas credentials` once to export a backup of the upload keystore.
- **Don't rename the package** after the first upload — it creates a different app.

---

## Appendix — Fully local release build (no Expo account)

Only if you want to avoid EAS entirely:

1. Generate an upload keystore (JDK 17's keytool):
   ```powershell
   & "$env:JAVA_HOME\bin\keytool" -genkeypair -v -keystore upload.keystore `
     -alias upload -keyalg RSA -keysize 2048 -validity 10000
   ```
   Store it OUTSIDE the repo (e.g. `C:\Users\Bill\keys\`) and back it up — losing it means a
   support ticket with Google to reset the upload key.
2. Because `android/` is generated (CNG), stop gitignoring it (`git add -f app/android` and
   remove `/android` from `app/.gitignore`) **or** re-apply signing config after every
   `prebuild --clean`. Committing `android/` is simpler once the project stabilizes.
3. Add to `android/gradle.properties` (never commit passwords — use
   `%USERPROFILE%\.gradle\gradle.properties` instead):
   ```
   INSTAPLAYER_UPLOAD_STORE_FILE=C:\\Users\\Bill\\keys\\upload.keystore
   INSTAPLAYER_UPLOAD_KEY_ALIAS=upload
   INSTAPLAYER_UPLOAD_STORE_PASSWORD=...
   INSTAPLAYER_UPLOAD_KEY_PASSWORD=...
   ```
4. In `android/app/build.gradle`, add a `release` signingConfig reading those properties and
   point `buildTypes.release.signingConfig` at it.
5. Build: `cd android; .\gradlew.bat bundleRelease` → `android/app/build/outputs/bundle/release/app-release.aab`.
6. versionCode must be bumped manually in `app.json` (`android.versionCode`) before each
   prebuild/upload.
