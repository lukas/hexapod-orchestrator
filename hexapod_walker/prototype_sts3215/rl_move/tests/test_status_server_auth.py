"""Authentication is checked even when a request bypasses proxy SSO."""
from types import SimpleNamespace

import pytest

import status_server as status


@pytest.fixture
def credentials(monkeypatch, tmp_path):
    secret = tmp_path / "signing-secret"
    secret.write_text("local-test-secret")
    monkeypatch.setattr(status, "SSO_SECRET_PATH", secret)
    monkeypatch.setattr(status, "TOKEN", "local-test-api-key")
    monkeypatch.setenv("STATUS_TRUST_PROXY_USER", "true")
    return secret


def authed(path="/now", **headers):
    return status.Handler._authed(SimpleNamespace(path=path, headers=headers))


@pytest.mark.parametrize("path,headers", [
    ("/now", {"Authorization": "Bearer invalid"}),
    ("/now?key=invalid", {}),
    ("/now", {}),
])
def test_forwarded_identity_cannot_bypass_auth(credentials, path, headers):
    headers["X-Hexapod-User"] = "lukas"
    assert not authed(path, **headers)


def test_signed_sso_cookie_authenticates_without_proxy_header(credentials):
    token = status.sso_token("lukas")
    assert authed(Cookie=f"hexapod_sso={token}")
    assert not authed(Cookie=f"hexapod_sso={token[:-1]}x")


def test_api_key_authentication_is_preserved(credentials):
    assert authed("/now?key=local-test-api-key")
    assert authed(Cookie="status_token=local-test-api-key")
    assert not authed(Cookie="status_token=invalid")


def test_expired_or_unverifiable_cookie_is_rejected(credentials, monkeypatch):
    monkeypatch.setattr(status.time, "time", lambda: 1000.0)
    token = status.sso_token("lukas")
    assert status.sso_verify(token, now=1001) == "lukas"
    assert status.sso_verify(token, now=1001 + status.SSO_MAX_AGE) is None
    credentials.unlink()
    assert not authed(Cookie=f"hexapod_sso={token}")


@pytest.mark.parametrize("signature", ["é" * 64, "z" * 64, "a", ""])
def test_malformed_signatures_fail_closed(credentials, signature):
    assert status.sso_verify("bHVrYXM=." + signature) is None
