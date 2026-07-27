"""Unit tests for the community-verification wiring.

No engine, no browser: these cover the session file (parsing, validity,
clearing), the solver command the engine is handed, and the environment
overrides that carry it across.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="musicapp-verify-"))

from app import verification  # noqa: E402
from app.config import Settings  # noqa: E402


def _settings(**overrides) -> Settings:
    return Settings(api_key="test-key", **overrides)


def _iso(delta: timedelta) -> str:
    # The engine writes RFC3339Nano — a trailing "Z", not "+00:00".
    return (datetime.now(timezone.utc) + delta).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    """Redirect the session path into tmp_path and hand back a writer."""
    path = tmp_path / ".spotiflac" / "community_session.json"
    path.parent.mkdir(parents=True)
    monkeypatch.setattr(verification, "session_path", lambda: path)

    def write(**fields):
        path.write_text(json.dumps(fields), encoding="utf-8")
        return path

    write.path = path
    return write


# --- session validity -----------------------------------------------------


def _record(expires_in: timedelta, **overrides) -> dict:
    return {
        "install_id": "abc123",
        "session_id": "sid",
        "session_secret": "shh",
        "expires_at": _iso(expires_in),
        **overrides,
    }


def test_valid_session():
    assert verification.session_is_valid(_record(timedelta(hours=2)))


def test_expired_session():
    assert not verification.session_is_valid(_record(timedelta(hours=-1)))


def test_session_inside_the_skew_is_already_dead():
    # Matches the engine: <5 min left counts as expired, so a download never
    # starts on credentials that die mid-run.
    assert not verification.session_is_valid(_record(timedelta(minutes=2)))
    assert verification.session_is_valid(_record(timedelta(minutes=20)))


def test_incomplete_session():
    assert not verification.session_is_valid(_record(timedelta(hours=2), session_id=""))
    assert not verification.session_is_valid(_record(timedelta(hours=2), session_secret=""))
    assert not verification.session_is_valid({"install_id": "abc"})
    assert not verification.session_is_valid(None)


def test_unparseable_expiry():
    assert not verification.session_is_valid(_record(timedelta(hours=2), expires_at="soon"))
    assert not verification.session_is_valid(_record(timedelta(hours=2), expires_at=""))


def test_naive_expiry_is_read_as_utc(session_file):
    naive = (datetime.now(timezone.utc) + timedelta(hours=2)).replace(tzinfo=None)
    assert verification.session_is_valid(
        _record(timedelta(0), expires_at=naive.isoformat())
    )


# --- reading and clearing -------------------------------------------------


def test_read_missing_session(session_file):
    session_file.path.unlink(missing_ok=True)
    assert verification.read_session() is None


def test_read_corrupt_session(session_file):
    session_file.path.write_text("{not json", encoding="utf-8")
    assert verification.read_session() is None


def test_clear_keeps_install_id(session_file):
    session_file(**_record(timedelta(hours=2)))
    assert verification.clear_session() is True

    record = verification.read_session()
    assert record["install_id"] == "abc123"  # engine reuses it; don't churn it
    assert record["session_id"] == ""
    assert record["session_secret"] == ""
    assert not verification.session_is_valid(record)


def test_clear_with_no_file_is_a_noop(session_file):
    session_file.path.unlink(missing_ok=True)
    assert verification.clear_session() is False


# --- the solver command ---------------------------------------------------


def test_default_command_uses_our_interpreter():
    argv = verification.solver_argv(_settings())
    assert argv[0] == sys.executable
    # The bridge, not the solver directly — it relays the grant to the engine
    # rather than trusting the challenge page to redirect.
    assert argv[1:3] == ["-m", "app.verify_cli"]
    assert "--hold-open" in argv
    assert "--diagnostics-dir" in argv


def test_hold_open_is_configurable():
    argv = verification.solver_argv(_settings(verify_hold_open=9.0))
    assert argv[argv.index("--hold-open") + 1] == "9.0"


def test_command_override_as_json_array():
    argv = verification.solver_argv(
        _settings(verify_command='["/usr/bin/solve", "--flag"]')
    )
    assert argv == ["/usr/bin/solve", "--flag"]


def test_command_override_as_command_line():
    argv = verification.solver_argv(_settings(verify_command="solve --flag"))
    assert argv == ["solve", "--flag"]


def test_malformed_json_override_falls_back_to_the_default():
    argv = verification.solver_argv(_settings(verify_command='["unterminated'))
    assert argv[0] == sys.executable


# --- engine environment ---------------------------------------------------


def test_env_carries_the_command_as_json(monkeypatch):
    monkeypatch.setattr(verification, "solver_ready", lambda: (True, None))
    env = verification.engine_env(_settings())
    assert json.loads(env["SPOTIFLAC_VERIFY_CMD"])[0] == sys.executable


def test_env_puts_the_package_root_on_pythonpath(monkeypatch):
    monkeypatch.setattr(verification, "solver_ready", lambda: (True, None))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = verification.engine_env(_settings())
    # `-m turnstile_solver` must resolve whatever the engine's cwd is.
    # backend/, which holds both app/ and turnstile_solver/.
    assert env["PYTHONPATH"] == str(Path(verification.__file__).resolve().parents[1])


def test_env_preserves_an_existing_pythonpath(monkeypatch):
    monkeypatch.setattr(verification, "solver_ready", lambda: (True, None))
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
    env = verification.engine_env(_settings())
    assert env["PYTHONPATH"].endswith(f"{os.pathsep}/somewhere/else")


def test_env_disables_verification_when_the_solver_is_unusable(monkeypatch):
    monkeypatch.setattr(verification, "solver_ready", lambda: (False, "no browser"))
    # Empty (not absent): the engine must not inherit a stale value from us.
    assert verification.engine_env(_settings()) == {"SPOTIFLAC_VERIFY_CMD": ""}


def test_env_disabled_by_setting(monkeypatch):
    monkeypatch.setattr(
        verification, "solver_ready", lambda: pytest.fail("should not probe the solver")
    )
    assert verification.engine_env(_settings(auto_verify=False)) == {
        "SPOTIFLAC_VERIFY_CMD": ""
    }


def test_custom_command_skips_the_solver_check(monkeypatch):
    monkeypatch.setattr(
        verification, "solver_ready", lambda: pytest.fail("admin's command, not ours")
    )
    env = verification.engine_env(_settings(verify_command="solve"))
    assert json.loads(env["SPOTIFLAC_VERIFY_CMD"]) == ["solve"]


# --- status report --------------------------------------------------------


def test_status_report_never_leaks_the_secret(session_file, monkeypatch):
    monkeypatch.setattr(verification, "solver_ready", lambda: (True, None))
    session_file(**_record(timedelta(hours=3)))

    report = verification.status_report(_settings())
    assert "shh" not in json.dumps(report)
    assert report["sessionPresent"] and report["sessionValid"]
    assert report["installId"] == "abc123"
    assert report["expiresInSeconds"] > 3500


def test_status_report_with_no_session(session_file, monkeypatch):
    monkeypatch.setattr(verification, "solver_ready", lambda: (True, None))
    session_file.path.unlink(missing_ok=True)

    report = verification.status_report(_settings())
    assert report["sessionPresent"] is False
    assert report["sessionValid"] is False
    assert report["expiresAt"] is None


def test_missing_browser_in_a_container_names_the_build_arg(monkeypatch):
    # "install a browser or set CHROME_PATH" is useless advice inside our own
    # image; the real cause is a build that dropped WITH_SOLVER.
    monkeypatch.setattr(verification, "_in_container", lambda: True)
    assert "WITH_SOLVER=1" in verification._browser_install_hint()


def test_no_container_hint_on_a_normal_host(monkeypatch):
    monkeypatch.setattr(verification, "_in_container", lambda: False)
    assert verification._browser_install_hint() == ""


def test_status_report_explains_a_missing_browser(session_file, monkeypatch):
    monkeypatch.setattr(verification, "solver_ready", lambda: (False, "no browser"))
    report = verification.status_report(_settings())
    assert report["solverReady"] is False
    assert report["solverError"] == "no browser"


def test_status_report_when_disabled(session_file):
    report = verification.status_report(_settings(auto_verify=False))
    assert report["autoVerify"] is False
    assert report["solverReady"] is False
    assert "disabled" in report["solverError"]
    assert report["solverCommand"] is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
