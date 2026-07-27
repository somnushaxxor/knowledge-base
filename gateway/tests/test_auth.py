from __future__ import annotations

from knowledge_gateway.auth import SINGLE_USER_ACTOR_ID, SingleUserTokenVerifier


async def test_single_user_verifier_accepts_only_configured_token() -> None:
    verifier = SingleUserTokenVerifier("configured-secret")

    accepted = await verifier.verify_token("configured-secret")

    assert accepted is not None
    assert accepted.client_id == SINGLE_USER_ACTOR_ID
    assert accepted.claims == {"sub": SINGLE_USER_ACTOR_ID}
    assert await verifier.verify_token("another-secret") is None
    assert await verifier.verify_token("") is None
