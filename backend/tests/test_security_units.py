"""Unit tests: passwords, tokens, rate limiter, CSRF, emails, Google client."""

import json
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.core.csrf import CsrfMiddleware
from app.core.rate_limit import MemoryRateLimiter
from app.core.security import (
    hash_password,
    hash_token,
    new_token,
    password_needs_rehash,
    verify_password,
)
from app.services import email as emails
from app.services import google_oauth
from app.services.auth import workspace_name
from app.services.google_oauth import GoogleAuthError, HttpGoogleClient, new_pkce_pair


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert "correct horse" not in hashed
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("wrong", hashed)
    assert not password_needs_rehash(hashed)


def test_verify_without_hash_is_false_even_for_dummy_password() -> None:
    assert not verify_password("not-a-real-password-just-for-timing", None)
    assert not verify_password("anything", "not-a-hash")


def test_tokens_are_random_and_hashed() -> None:
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 40
    assert hash_token(a) == hash_token(a) and len(hash_token(a)) == 64 and hash_token(a) != a


async def test_memory_rate_limiter() -> None:
    limiter = MemoryRateLimiter()
    results = [await limiter.hit("k", limit=3, window_seconds=60) for _ in range(4)]
    assert results[:3] == [None, None, None]
    assert results[3] is not None and results[3] > 0
    assert (await limiter.count("k"))[0] == 4
    await limiter.reset("k")
    assert (await limiter.count("k"))[0] == 0


def _csrf_app() -> Any:
    async def ok(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/x", ok, methods=["GET", "POST"])])
    return CsrfMiddleware(app, cookie_name="session", allowed_origins={"http://localhost:3000"})


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 200),  # no cookie: not a browser session (e.g. API key)
        ({"cookie": "session=t", "origin": "http://localhost:3000"}, 200),
        ({"cookie": "session=t", "origin": "https://evil.example"}, 403),
        ({"cookie": "session=t", "referer": "https://evil.example/page"}, 403),
        ({"cookie": "session=t", "origin": "null", "referer": "https://evil.example/"}, 403),
        ({"cookie": "session=t"}, 200),  # non-browser client without Origin
        ({"cookie": "other=1", "origin": "https://evil.example"}, 200),
    ],
)
async def test_csrf_middleware(headers: dict[str, str], expected: int) -> None:
    async with AsyncClient(transport=ASGITransport(app=_csrf_app()), base_url="http://test") as c:
        res = await c.post("/x", headers=headers)
        get = await c.get("/x", headers=headers)
    assert res.status_code == expected
    assert get.status_code == 200  # safe methods are never blocked
    if expected == 403:
        assert res.json()["error"]["code"] == "csrf_failed"


def test_verification_email_contains_link_and_escapes_name() -> None:
    msg = emails.verification_email(
        to="a@example.com",
        name="<b>Eve</b>",
        url="http://localhost:3000/verify-email?token=abc",
        app_name="Foundation",
        hours=48,
    )
    assert "http://localhost:3000/verify-email?token=abc" in msg.text
    assert msg.html is not None and "<b>Eve</b>" not in msg.html and "&lt;b&gt;" in msg.html


def test_workspace_name() -> None:
    assert workspace_name("Ezat Hotak") == "Ezat's workspace"
    assert workspace_name("   ") == "My's workspace" or workspace_name("   ").endswith("workspace")


def test_pkce_pair() -> None:
    verifier, challenge = new_pkce_pair()
    assert len(verifier) >= 43 and "=" not in challenge and verifier != challenge


def test_google_authorize_url() -> None:
    url = HttpGoogleClient("cid", "secret").authorize_url(
        state="s1", code_challenge="c1", redirect_uri="http://x/cb"
    )
    assert url.startswith(google_oauth.AUTHORIZE_URL)
    for part in (
        "client_id=cid",
        "state=s1",
        "code_challenge=c1",
        "code_challenge_method=S256",
        "scope=openid+email+profile",
    ):
        assert part in url
    assert "secret" not in url


def _mock_google(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    real = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_google_fetch_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == google_oauth.TOKEN_URL:
            seen["form"] = dict(httpx.QueryParams(request.content.decode()))
            return httpx.Response(200, json={"access_token": "at"})
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200, json={"sub": "1", "email": "g@example.com", "email_verified": True, "name": "G"}
        )

    _mock_google(monkeypatch, handler)
    profile = await HttpGoogleClient("cid", "sec").fetch_profile(
        code="c", code_verifier="v", redirect_uri="http://x/cb"
    )
    assert (profile.sub, profile.email, profile.email_verified) == ("1", "g@example.com", True)
    assert seen["form"]["code_verifier"] == "v" and seen["auth"] == "Bearer at"


async def test_google_token_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_google(
        monkeypatch, lambda r: httpx.Response(400, content=json.dumps({"error": "invalid_grant"}))
    )
    with pytest.raises(GoogleAuthError):
        await HttpGoogleClient("cid", "sec").fetch_profile(
            code="c", code_verifier="v", redirect_uri="x"
        )
