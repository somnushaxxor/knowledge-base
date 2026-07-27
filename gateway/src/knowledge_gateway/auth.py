"""Authentication for the single-user Knowledge Gateway profile."""

from __future__ import annotations

import secrets

from fastmcp.server.auth import AccessToken, TokenVerifier


SINGLE_USER_ACTOR_ID = "single-user"


class SingleUserTokenVerifier(TokenVerifier):
    """Accept exactly one operator-configured opaque bearer token."""

    def __init__(self, access_token: str):
        super().__init__()
        self._access_token = access_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token, self._access_token):
            return None
        return AccessToken(
            token=token,
            client_id=SINGLE_USER_ACTOR_ID,
            scopes=[],
            claims={"sub": SINGLE_USER_ACTOR_ID},
        )
