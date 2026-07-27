"""Unit tests for the turnstile_solver package.

Browser-free by design: everything here exercises the pure logic (grant
extraction, sitekey scraping, config resolution, caching, the event-loop
guard). Actually driving Chrome is out of scope for the test suite.
"""
import asyncio
import os

import pytest

from turnstile_solver import (
    BrowserNotFoundError,
    DisplayUnavailableError,
    SolveResult,
    SolverConfig,
    TurnstileSolver,
    clear_cache,
    extract_grant,
    find_browser,
    sitekey_from_html,
)
from turnstile_solver import config as config_module
from turnstile_solver import solver as solver_module

KEYS = ("grant", "token", "code")


# --- grant extraction -----------------------------------------------------


def test_grant_from_query():
    assert extract_grant("http://127.0.0.1:5/cb?state=ab&grant=G-123", KEYS) == "G-123"


def test_grant_from_fragment():
    assert extract_grant("https://host/done#token=T-9", KEYS) == "T-9"


def test_grant_key_priority():
    # "grant" wins over "token"/"code" regardless of order in the URL.
    url = "https://host/cb?code=C&token=T&grant=G"
    assert extract_grant(url, KEYS) == "G"


def test_grant_absent_or_blank():
    assert extract_grant("https://host/cb?state=ab", KEYS) is None
    assert extract_grant("https://host/cb?grant=", KEYS) is None
    assert extract_grant("", KEYS) is None


def test_grant_respects_custom_keys():
    assert extract_grant("https://host/cb?ticket=X", ("ticket",)) == "X"
    assert extract_grant("https://host/cb?ticket=X", KEYS) is None


# --- sitekey scraping -----------------------------------------------------


def test_sitekey_from_attribute():
    html = '<div class="cf-turnstile" data-sitekey="0x4AAAAAAABbbbCc"></div>'
    assert sitekey_from_html(html) == "0x4AAAAAAABbbbCc"


def test_sitekey_from_inline_script():
    html = "<script>turnstile.render('#x', { sitekey: '0x4AAAAAAAdddEee' })</script>"
    assert sitekey_from_html(html) == "0x4AAAAAAAdddEee"


def test_sitekey_from_query_string():
    assert sitekey_from_html("<a href='/c?sitekey=0x4AAAAAAAfff'>go</a>") == "0x4AAAAAAAfff"


def test_sitekey_missing():
    assert sitekey_from_html("<html><body>nothing here</body></html>") is None
    # Too short to be a real sitekey — don't hand back junk.
    assert sitekey_from_html('<div data-sitekey="abc"></div>') is None


# --- config ---------------------------------------------------------------


def test_offscreen_flags_toggle():
    assert any("--window-position" in a for a in SolverConfig().chrome_args())
    assert not any(
        "--window-position" in a for a in SolverConfig(offscreen=False).chrome_args()
    )


def test_first_run_flags_are_always_present():
    # A first-run interstitial can replace the tab nodriver is about to drive.
    for args in (SolverConfig().chrome_args(), SolverConfig().chrome_args(headless=True)):
        assert "--no-first-run" in args
        assert "--disable-session-crashed-bubble" in args


def test_site_isolation_flag_is_dropped_by_default():
    # Turnstile's widget is a cross-origin iframe; disabling site isolation
    # (nodriver's default) is not neutral for it.
    assert any(
        "site-per-process" in prefix for prefix in SolverConfig().drop_browser_args
    )


def test_throttling_is_disabled_in_every_mode():
    # A throttled renderer never runs the countdown the challenge page hides
    # its widget behind, so no captcha ever appears.
    for args in (SolverConfig().chrome_args(), SolverConfig().chrome_args(headless=True)):
        assert "--disable-background-timer-throttling" in args
        assert "--disable-backgrounding-occluded-windows" in args
        assert "--disable-renderer-backgrounding" in args


def test_widget_wait_clears_a_countdown():
    # SpotiFLAC's challenge page counts down ~5s before arming Turnstile.
    assert SolverConfig().widget_wait >= 15.0


def test_attempt_outlasts_the_verifying_spinner():
    # A click puts the widget into "Verifying…" for several seconds; the
    # attempt has to still be running when the token lands.
    config = SolverConfig()
    assert config.attempt_timeout >= config.click_interval + 10


def test_clicks_are_conservative():
    # Clicking a widget mid-verification can reset it.
    assert SolverConfig().max_clicks <= 2


def test_watching_comes_before_clicking():
    # A managed widget verifies unprompted; the attempt must leave room to
    # watch it work, and still have time to click afterwards.
    config = SolverConfig()
    assert config.pre_click_wait > 0
    assert config.attempt_timeout > config.pre_click_wait + config.click_interval


def test_adopted_display_still_counts_as_virtual(monkeypatch):
    # A process that adopts a display another one left running owns no
    # process handle, but it is still on a virtual screen — miss that and the
    # window gets parked off-screen with no window manager to draw it.
    monkeypatch.setattr(config_module, "_xvfb_process", None)
    monkeypatch.setattr(config_module, "_on_virtual_display", True)
    assert config_module.virtual_display_active() is True


def test_no_offscreen_parking_on_our_own_xvfb(monkeypatch):
    # Nobody to hide from on a virtual display, and a window at -32000 with no
    # window manager can leave the renderer unpainted.
    monkeypatch.setattr(config_module, "virtual_display_active", lambda: True)
    args = SolverConfig().chrome_args()
    assert not any("--window-position" in a for a in args)
    assert "--window-size=1920,1080" in args


def test_extra_browser_args_are_appended_last():
    args = SolverConfig(browser_args=("--lang=en-US",)).chrome_args()
    assert args[-1] == "--lang=en-US"


def test_find_browser_prefers_explicit_then_env(monkeypatch):
    monkeypatch.setenv("CHROME_PATH", r"C:\env\chrome.exe")
    assert find_browser(r"C:\explicit\chrome.exe") == r"C:\explicit\chrome.exe"
    assert find_browser(None) == r"C:\env\chrome.exe"


def test_find_browser_raises_when_nothing_found(monkeypatch):
    for var in ("CHROME_PATH", "BRAVE_PATH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("turnstile_solver.config._BROWSER_CANDIDATES", {})
    monkeypatch.setattr("turnstile_solver.config.shutil.which", lambda _cmd: None)
    with pytest.raises(BrowserNotFoundError):
        find_browser()


def test_headless_adds_gpu_flag_and_drops_window_placement():
    args = SolverConfig().chrome_args(headless=True)
    assert "--disable-gpu" in args
    assert not any("--window-position" in a for a in args)


# --- profile locks --------------------------------------------------------


def test_stale_singleton_markers_are_removed(tmp_path):
    # A killed container leaves these behind; Chrome then tries to hand the URL
    # to an instance that no longer exists and we never get our tab.
    (tmp_path / "SingletonLock").write_text("stale")
    (tmp_path / "SingletonCookie").write_text("stale")
    keep = tmp_path / "Default"
    keep.mkdir()

    config_module.clear_stale_profile_locks(str(tmp_path))

    assert not (tmp_path / "SingletonLock").exists()
    assert not (tmp_path / "SingletonCookie").exists()
    assert keep.is_dir()  # the profile itself must survive


def test_clearing_locks_tolerates_a_missing_profile(tmp_path):
    config_module.clear_stale_profile_locks(str(tmp_path / "not-created-yet"))


# --- headless / display resolution ---------------------------------------


@pytest.fixture
def linux_headless(monkeypatch):
    """A Linux host with no DISPLAY and no Xvfb, unless a test says otherwise."""
    monkeypatch.setattr("turnstile_solver.config.platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("TS_HEADLESS", raising=False)
    started = []

    def fake_start(display, screen, binary):
        started.append((display, screen, binary))
        return False

    monkeypatch.setattr(config_module, "start_virtual_display", fake_start)
    return started


def test_auto_prefers_a_real_display(monkeypatch):
    monkeypatch.delenv("TS_HEADLESS", raising=False)
    monkeypatch.setattr("turnstile_solver.config.platform.system", lambda: "Linux")
    monkeypatch.setenv("DISPLAY", ":0")
    # A display already exists, so Xvfb must not be touched.
    monkeypatch.setattr(
        config_module,
        "start_virtual_display",
        lambda *a: pytest.fail("should not start Xvfb when DISPLAY is set"),
    )
    assert SolverConfig().resolve_headless() is False


def test_auto_uses_xvfb_when_it_starts(linux_headless, monkeypatch):
    monkeypatch.setattr(
        config_module, "start_virtual_display", lambda *a: True
    )
    assert SolverConfig().resolve_headless() is False


def test_auto_falls_back_to_headless_without_xvfb(linux_headless):
    assert SolverConfig().resolve_headless() is True
    assert linux_headless == [(":99", "1920x1080x24", "Xvfb")]


def test_xvfb_settings_are_passed_through(linux_headless):
    SolverConfig(xvfb_display=":7", xvfb_screen="1920x1080x24").resolve_headless()
    assert linux_headless == [(":7", "1920x1080x24", "Xvfb")]


def test_use_xvfb_false_skips_the_virtual_display(linux_headless):
    assert SolverConfig(use_xvfb=False).resolve_headless() is True
    assert linux_headless == []


def test_explicit_headless_skips_display_machinery(linux_headless):
    assert SolverConfig(headless=True).resolve_headless() is True
    assert linux_headless == []


def test_no_headless_refuses_to_degrade(linux_headless):
    with pytest.raises(DisplayUnavailableError):
        SolverConfig(headless=False).resolve_headless()


def test_non_linux_is_never_headless_under_auto(monkeypatch):
    monkeypatch.delenv("TS_HEADLESS", raising=False)
    monkeypatch.setattr("turnstile_solver.config.platform.system", lambda: "Windows")
    monkeypatch.delenv("DISPLAY", raising=False)
    assert SolverConfig().resolve_headless() is False


@pytest.mark.parametrize(
    "value,expected",
    [("1", True), ("true", True), ("on", True), ("0", False), ("false", False)],
)
def test_ts_headless_env_overrides_auto(linux_headless, monkeypatch, value, expected):
    monkeypatch.setenv("TS_HEADLESS", value)
    if expected:
        assert SolverConfig().resolve_headless() is True
    else:
        # TS_HEADLESS=0 means "insist on a display" — same as headless=False.
        with pytest.raises(DisplayUnavailableError):
            SolverConfig().resolve_headless()


def test_ts_headless_does_not_override_an_explicit_setting(linux_headless, monkeypatch):
    monkeypatch.setenv("TS_HEADLESS", "1")
    with pytest.raises(DisplayUnavailableError):
        SolverConfig(headless=False).resolve_headless()


def test_junk_ts_headless_is_ignored(linux_headless, monkeypatch):
    monkeypatch.setenv("TS_HEADLESS", "maybe")
    assert SolverConfig().resolve_headless() is True  # falls through to auto


def test_virtual_display_reports_failure_when_xvfb_is_missing(monkeypatch):
    monkeypatch.setattr("turnstile_solver.config.platform.system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr("turnstile_solver.config.shutil.which", lambda _b: None)
    assert config_module.start_virtual_display() is False
    assert "DISPLAY" not in os.environ


def test_virtual_display_is_a_noop_when_display_exists(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(
        "turnstile_solver.config.shutil.which",
        lambda _b: pytest.fail("should not look for Xvfb"),
    )
    assert config_module.start_virtual_display() is True


def test_per_call_overrides_do_not_mutate_the_solver():
    solver = TurnstileSolver(SolverConfig(attempts=3))
    assert solver._config_for({"attempts": 9}).attempts == 9
    assert solver.config.attempts == 3


# --- result ---------------------------------------------------------------


def test_result_truthiness_and_value():
    assert not SolveResult()
    assert SolveResult(token="T")
    assert SolveResult(grant="G")
    # The grant is what a caller ultimately wants when both are present.
    assert SolveResult(token="T", grant="G").value == "G"
    assert SolveResult(token="T").value == "T"
    assert SolveResult().value == ""


# --- cache ----------------------------------------------------------------


def test_cache_only_applies_to_plain_token_solves():
    cacheable = TurnstileSolver._cacheable
    assert cacheable(SolverConfig(capture_grant=False))
    # A cached token replays no page load, so it can produce neither a grant
    # nor the post-success side effects hold_open waits for.
    assert not cacheable(SolverConfig(capture_grant=True))
    assert not cacheable(SolverConfig(capture_grant=False, hold_open=2.0))
    assert not cacheable(SolverConfig(capture_grant=False, cache_ttl=0))


def test_cache_expires():
    clear_cache()
    key = ("sk", "https://host/c")
    solver_module._cache[key] = (0.0, "stale-token")  # epoch 0 → long expired
    assert TurnstileSolver._cache_get(key, ttl=900) is None
    assert key not in solver_module._cache
    clear_cache()


def test_clear_cache():
    solver_module._cache[("sk", "u")] = (9e12, "tok")  # far-future timestamp
    assert TurnstileSolver._cache_get(("sk", "u"), ttl=900) == "tok"
    clear_cache()
    assert TurnstileSolver._cache_get(("sk", "u"), ttl=900) is None


# --- event-loop guard -----------------------------------------------------


def test_sync_solve_refuses_to_block_a_running_loop():
    async def inner():
        with pytest.raises(RuntimeError, match="event loop"):
            TurnstileSolver().solve("https://host/c")

    asyncio.run(inner())


if __name__ == "__main__":
    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
