"""
Shared test fixtures.

- Stubs out env vars the connectors expect, so import / construction never
  reads the developer's real .env.
- Blocks raw socket use during the test session: any test that forgets to
  mock requests will fail loudly instead of silently hitting prod APIs.
- Resets the cached config between tests so config edits don't leak.
"""
import os
import socket
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


_FAKE_ENV = {
    "ATLASSIAN_EMAIL": "tester@example.com",
    "ATLASSIAN_BASE_URL": "https://example.atlassian.net",
    "CONFLUENCE_API_TOKEN": "fake-token",
    "JIRA_API_TOKEN": "fake-token",
    "GITHUB_TOKEN": "fake-token",
    "SLACK_BOT_TOKEN": "xoxb-fake",
    "SLACK_USER_TOKEN": "xoxp-fake",
    "ANTHROPIC_API_KEY": "fake-key",
    "NEWSAPI_KEY": "fake-key",
}


@pytest.fixture(autouse=True)
def _fake_env(monkeypatch):
    for k, v in _FAKE_ENV.items():
        monkeypatch.setenv(k, v)


@pytest.fixture(autouse=True)
def _reset_config_cache():
    """Clear src.config's module-level cache so each test gets a fresh load."""
    import src.config as cfg
    cfg._config_cache = None
    yield
    cfg._config_cache = None


def _block_socket(*args, **kwargs):
    raise RuntimeError(
        "Real network call blocked in tests. Mock requests with the `responses` "
        "fixture or monkeypatch the call."
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if a test forgets to mock and tries a real socket connect."""
    monkeypatch.setattr(socket.socket, "connect", _block_socket)
