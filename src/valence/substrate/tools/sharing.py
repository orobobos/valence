"""Sharing tool implementations.

Functions:
    belief_share, belief_shares_list, belief_share_revoke,
    _get_local_did, _validate_enum (re-exported from _common)
"""

from __future__ import annotations

from typing import Any

from . import _common
from ._common import _validate_enum, datetime, hashlib, json, os


def _get_local_did() -> str:
    """Get the local DID for signing. Cycle 2 wires our-identity."""
    return os.environ.get("VALENCE_LOCAL_DID", "did:valence:local")


def belief_share(
    belief_id: str,
    recipient_did: str,
    intent: str = "know_me",
    max_hops: int | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Share a belief with a specific person.

    Creates a consent chain and share record. The intent controls the
    generated SharePolicy (enforcement level, propagation rules).

    Cycle 1: Uses placeholder signatures and unencrypted envelopes.
    Cycle 2: Adds real Ed25519 signing and PRE encryption.
    """
    from our_privacy.types import IntentConfig, SharePolicy, SharingIntent

    # --- Input validation ---
    valid_intents = ["know_me", "work_with_me", "learn_from_me", "use_this"]
    if err := _validate_enum(intent, valid_intents, "intent"):
        return err

    parsed_expires = None
    if expires_at:
        try:
            parsed_expires = datetime.fromisoformat(expires_at)
        except ValueError:
            return {"success": False, "error": f"Invalid expires_at format: '{expires_at}'. Must be ISO 8601."}

    with _common.get_cursor() as cur:
        # Verify belief exists and get content + share_policy + holder_id
        cur.execute("SELECT id, content, share_policy, holder_id FROM beliefs WHERE id = %s", (belief_id,))
        belief_row = cur.fetchone()
        if not belief_row:
            return {"success": False, "error": f"Belief not found: {belief_id}"}

        # --- Ownership check (#337) ---
        # NULL holder_id = locally created, permissive (backward compat)
        # Non-NULL holder_id = explicit owner entity, must match local identity
        holder_id = belief_row.get("holder_id")
        if holder_id is not None:
            # Belief has explicit ownership. Verify current node owns it.
            # Cycle 3 wires proper DID<->entity resolution via our-identity.
            # For now, check against VALENCE_LOCAL_ENTITY_ID env var.
            local_entity_id = os.environ.get("VALENCE_LOCAL_ENTITY_ID")
            if local_entity_id is None or str(holder_id) != local_entity_id:
                return {
                    "success": False,
                    "error": f"Cannot share belief {belief_id}: you are not the holder of this belief",
                }

        # --- Reshare policy check (#337) ---
        existing_policy_data = belief_row.get("share_policy")
        if existing_policy_data:
            if isinstance(existing_policy_data, str):
                existing_policy_data = json.loads(existing_policy_data)
            # IntentConfig.to_dict() stores the policy under a "policy" key
            policy_dict = existing_policy_data.get("policy", existing_policy_data)
            existing_share_policy = SharePolicy.from_dict(policy_dict)
            if existing_share_policy.is_expired():
                return {"success": False, "error": "Belief's share policy has expired — sharing is no longer permitted"}
            if not existing_share_policy.allows_sharing_to(recipient_did):
                return {"success": False, "error": f"Belief's share policy does not allow sharing to {recipient_did}"}

        # Build IntentConfig
        intent_config = IntentConfig(
            intent=SharingIntent(intent),
            recipients=[recipient_did],
            max_hops=max_hops,
            expires_at=parsed_expires,
        )
        share_policy = intent_config.to_share_policy()

        local_did = _get_local_did()

        # Placeholder signature (Cycle 2: real Ed25519)
        chain_hash = hashlib.sha256(f"{belief_id}:{local_did}:{recipient_did}:{intent}".encode()).digest()

        # Insert consent chain
        cur.execute(
            """
            INSERT INTO consent_chains (belief_id, origin_sharer, origin_timestamp, origin_policy, origin_signature, chain_hash)
            VALUES (%s, %s, NOW(), %s, %s, %s)
            RETURNING id
            """,
            (
                belief_id,
                local_did,
                json.dumps(intent_config.to_dict()),
                chain_hash,
                chain_hash,
            ),
        )
        consent_chain_id = cur.fetchone()["id"]

        # Placeholder encrypted envelope (Cycle 2: real PRE encryption)
        encrypted_envelope = {
            "algorithm": "none",
            "content": belief_row["content"],
            "note": "Cycle 1 placeholder — unencrypted. Cycle 2 adds PRE encryption.",
        }

        # Insert share (handle duplicate)
        try:
            cur.execute(
                """
                INSERT INTO shares (consent_chain_id, encrypted_envelope, recipient_did, intent, belief_id)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    str(consent_chain_id),
                    json.dumps(encrypted_envelope),
                    recipient_did,
                    intent,
                    belief_id,
                ),
            )
            share_id = cur.fetchone()["id"]
        except Exception as e:
            # Check for unique constraint violation (psycopg2.errors.UniqueViolation)
            err_name = type(e).__name__
            if err_name == "UniqueViolation" or "unique" in str(e).lower() or "duplicate" in str(e).lower():
                return {"success": False, "error": "Belief already shared with this recipient"}
            raise

        # Update belief's share_policy — only set when currently NULL (preserves original intent)
        cur.execute(
            "UPDATE beliefs SET share_policy = COALESCE(share_policy, %s), modified_at = NOW() WHERE id = %s",
            (json.dumps(intent_config.to_dict()), belief_id),
        )

        return {
            "success": True,
            "share_id": str(share_id),
            "consent_chain_id": str(consent_chain_id),
            "recipient": recipient_did,
            "intent": intent,
            "policy": share_policy.to_dict(),
            "belief_content": belief_row["content"],
        }


def belief_shares_list(
    direction: str = "outgoing",
    include_revoked: bool = False,
    limit: int = 20,
    belief_id: str | None = None,
) -> dict[str, Any]:
    """List shares -- outgoing or incoming.

    Uses the local DID to determine ownership.
    """
    # --- Input validation ---
    if err := _validate_enum(direction, ["outgoing", "incoming"], "direction"):
        return err

    local_did = _get_local_did()

    with _common.get_cursor() as cur:
        if direction == "outgoing":
            sql = """
                SELECT s.id as share_id, s.recipient_did, s.intent, s.belief_id,
                       s.created_at, s.access_count,
                       cc.origin_sharer, cc.revoked, cc.revoked_at, cc.revocation_reason,
                       b.content as belief_content
                FROM shares s
                JOIN consent_chains cc ON s.consent_chain_id = cc.id
                LEFT JOIN beliefs b ON s.belief_id = b.id
                WHERE cc.origin_sharer = %s
            """
        else:
            sql = """
                SELECT s.id as share_id, s.recipient_did, s.intent, s.belief_id,
                       s.created_at, s.access_count,
                       cc.origin_sharer, cc.revoked, cc.revoked_at, cc.revocation_reason,
                       b.content as belief_content
                FROM shares s
                JOIN consent_chains cc ON s.consent_chain_id = cc.id
                LEFT JOIN beliefs b ON s.belief_id = b.id
                WHERE s.recipient_did = %s
            """

        params: list[Any] = [local_did]

        if belief_id:
            sql += " AND s.belief_id = %s"
            params.append(belief_id)

        if not include_revoked:
            sql += " AND cc.revoked = false"

        sql += " ORDER BY s.created_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(sql, params)
        rows = cur.fetchall()

        shares = []
        for row in rows:
            shares.append({
                "share_id": str(row["share_id"]),
                "belief_id": str(row["belief_id"]) if row["belief_id"] else None,
                "belief_content": row.get("belief_content"),
                "recipient_did": row["recipient_did"],
                "origin_sharer": row["origin_sharer"],
                "intent": row["intent"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "access_count": row["access_count"],
                "revoked": row["revoked"],
                "revoked_at": row["revoked_at"].isoformat() if row.get("revoked_at") else None,
                "revocation_reason": row.get("revocation_reason"),
            })

        return {
            "success": True,
            "direction": direction,
            "shares": shares,
            "total_count": len(shares),
        }


def belief_share_revoke(
    share_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Revoke a share by marking its consent chain as revoked."""
    local_did = _get_local_did()

    with _common.get_cursor() as cur:
        # Look up share and its consent chain
        cur.execute(
            """
            SELECT s.id, s.consent_chain_id, cc.origin_sharer, cc.revoked
            FROM shares s
            JOIN consent_chains cc ON s.consent_chain_id = cc.id
            WHERE s.id = %s
            """,
            (share_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": f"Share not found: {share_id}"}

        if row["revoked"]:
            return {"success": False, "error": "Share is already revoked"}

        if row["origin_sharer"] != local_did:
            return {"success": False, "error": "Cannot revoke a share you did not create"}

        # Revoke the consent chain
        cur.execute(
            """
            UPDATE consent_chains
            SET revoked = true, revoked_at = NOW(), revoked_by = %s, revocation_reason = %s
            WHERE id = %s
            """,
            (local_did, reason, row["consent_chain_id"]),
        )

        return {
            "success": True,
            "share_id": share_id,
            "consent_chain_id": str(row["consent_chain_id"]),
            "revoked": True,
            "reason": reason,
        }
