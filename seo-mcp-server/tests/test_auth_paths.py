"""Credential path resolution.

The bug these guard against: paths resolving against the working directory.
MCP clients spawn the server from an arbitrary cwd, so a credential file
found during local development vanished when launched from a client.
"""

import os
import stat
import sys

import pytest

from seo_mcp_server.auth import google_oauth as go


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """
    Fully isolates credential resolution from the developer's machine.

    PACKAGE_ROOT must be redirected too: it's a real fallback location, so
    without this a stray token.json in the repo changes what these tests
    resolve to - and a test that writes a token would deposit one there,
    silently breaking every later run.
    """
    for var in (go.HOME_ENV, go.CLIENT_SECRET_ENV, go.TOKEN_ENV):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(go.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(go, "PACKAGE_ROOT", tmp_path / "not-a-real-repo")
    return tmp_path


class TestPathResolution:
    def test_defaults_into_app_home(self, clean_env):
        mgr = go.GoogleAuthManager()
        assert mgr.client_secrets_path == clean_env / ".seo-mcp" / "client_secret.json"
        assert mgr.token_path == clean_env / ".seo-mcp" / "token.json"

    def test_ignores_working_directory(self, clean_env, tmp_path, monkeypatch):
        """The regression test: cwd must not influence resolution."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        before = go.GoogleAuthManager().client_secrets_path
        monkeypatch.chdir(elsewhere)
        assert go.GoogleAuthManager().client_secrets_path == before

    def test_home_env_redirects_both_files(self, clean_env, tmp_path, monkeypatch):
        custom = tmp_path / "custom-home"
        monkeypatch.setenv(go.HOME_ENV, str(custom))
        mgr = go.GoogleAuthManager()
        assert mgr.client_secrets_path == custom / "client_secret.json"
        assert mgr.token_path == custom / "token.json"

    def test_explicit_env_vars_win(self, clean_env, tmp_path, monkeypatch):
        cs, tok = tmp_path / "a.json", tmp_path / "b.json"
        monkeypatch.setenv(go.CLIENT_SECRET_ENV, str(cs))
        monkeypatch.setenv(go.TOKEN_ENV, str(tok))
        mgr = go.GoogleAuthManager()
        assert mgr.client_secrets_path == cs
        assert mgr.token_path == tok

    def test_constructor_argument_beats_environment(self, clean_env, tmp_path, monkeypatch):
        monkeypatch.setenv(go.CLIENT_SECRET_ENV, str(tmp_path / "from-env.json"))
        explicit = tmp_path / "explicit.json"
        assert go.GoogleAuthManager(client_secrets_path=str(explicit)).client_secrets_path == explicit

    def test_existing_file_is_preferred_over_default(self, clean_env, monkeypatch, tmp_path):
        """A repo-local credential file is still found, for local development."""
        repo = tmp_path / "repo"
        repo.mkdir()
        legacy = repo / "client_secret.json"
        legacy.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(go, "PACKAGE_ROOT", repo)
        assert go.GoogleAuthManager().client_secrets_path == legacy

    def test_search_order_is_most_explicit_first(self, clean_env, monkeypatch, tmp_path):
        monkeypatch.setenv(go.CLIENT_SECRET_ENV, str(tmp_path / "env.json"))
        found = go._candidates(go.DEFAULT_CLIENT_SECRETS_FILE, go.CLIENT_SECRET_ENV)
        assert found[0] == tmp_path / "env.json"
        assert found[1] == clean_env / ".seo-mcp" / "client_secret.json"


class TestTokenWriting:
    class FakeCreds:
        def to_json(self):
            return '{"refresh_token": "secret"}'

    def test_creates_parent_directory(self, clean_env):
        mgr = go.GoogleAuthManager()
        assert not mgr.token_path.parent.exists()
        mgr._save_token(self.FakeCreds())
        assert mgr.token_path.exists()
        assert "refresh_token" in mgr.token_path.read_text(encoding="utf-8")

    def test_overwrites_cleanly(self, clean_env):
        mgr = go.GoogleAuthManager()
        mgr._save_token(self.FakeCreds())
        mgr._save_token(self.FakeCreds())
        assert mgr.token_path.read_text(encoding="utf-8").count("refresh_token") == 1

    @pytest.mark.skipif(sys.platform == "win32",
                        reason="POSIX permission bits are not meaningful on Windows")
    def test_token_is_owner_only(self, clean_env):
        mgr = go.GoogleAuthManager()
        mgr._save_token(self.FakeCreds())
        assert stat.S_IMODE(os.stat(mgr.token_path).st_mode) == 0o600

    @pytest.mark.skipif(sys.platform == "win32",
                        reason="POSIX permission bits are not meaningful on Windows")
    def test_tightens_permissions_on_a_preexisting_loose_file(self, clean_env):
        mgr = go.GoogleAuthManager()
        mgr.token_path.parent.mkdir(parents=True, exist_ok=True)
        mgr.token_path.write_text("{}", encoding="utf-8")
        os.chmod(mgr.token_path, 0o644)
        mgr._save_token(self.FakeCreds())
        assert stat.S_IMODE(os.stat(mgr.token_path).st_mode) == 0o600


def test_scopes_are_read_only():
    """Widening these would let the server mutate the user's Google account."""
    assert all(s.endswith(".readonly") for s in go.SCOPES)
