"""Google sign-in (OpenID Connect, authorization code flow with PKCE).

Flow:
1. /api/auth/google/start  -> we redirect to Google with a random `state` and a PKCE challenge
   (both remembered in a short-lived httpOnly cookie).
2. Google redirects back to /api/auth/google/callback?code=...&state=...
3. We check `state`, exchange the code (server to server, over TLS) and read the profile
   from Google's userinfo endpoint. Only a *verified* Google email can sign in or link.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleAuthError(Exception):
    """Google sign-in failed (user cancelled, bad code, network problem, ...)."""


@dataclass(frozen=True)
class GoogleProfile:
    """What we use from the Google account."""

    sub: str
    email: str
    email_verified: bool
    name: str


def new_pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) for PKCE with S256."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class GoogleClient(Protocol):
    """Talks to Google. Tests use a fake."""

    def authorize_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        """Where to send the browser."""
        ...

    async def fetch_profile(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> GoogleProfile:
        """Exchange the code and return the user's profile."""
        ...


class HttpGoogleClient:
    """Real client (httpx)."""

    def __init__(self, client_id: str, client_secret: str, timeout: float = 10.0) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout

    def authorize_url(self, *, state: str, code_challenge: str, redirect_uri: str) -> str:
        """Google's consent screen URL."""
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def fetch_profile(
        self, *, code: str, code_verifier: str, redirect_uri: str
    ) -> GoogleProfile:
        """Code -> access token -> userinfo."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                token_res = await client.post(
                    TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                        "code_verifier": code_verifier,
                    },
                )
                if token_res.status_code != 200:
                    raise GoogleAuthError(f"token endpoint answered {token_res.status_code}")
                access_token = token_res.json().get("access_token")
                if not isinstance(access_token, str):
                    raise GoogleAuthError("no access token")
                info_res = await client.get(
                    USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
                )
                if info_res.status_code != 200:
                    raise GoogleAuthError(f"userinfo answered {info_res.status_code}")
                info = info_res.json()
        except httpx.HTTPError as exc:
            raise GoogleAuthError(type(exc).__name__) from exc
        sub, email = info.get("sub"), info.get("email")
        if not isinstance(sub, str) or not isinstance(email, str):
            raise GoogleAuthError("profile without sub/email")
        name = info.get("name") if isinstance(info.get("name"), str) else email.split("@")[0]
        return GoogleProfile(
            sub=sub, email=email, email_verified=info.get("email_verified") is True, name=name
        )
