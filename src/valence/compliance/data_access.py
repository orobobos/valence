"""GDPR data access (Article 15) and data portability (Article 20).

Article 15 - Right of access: Data subjects can request all personal data held.
Article 20 - Right to data portability: Data subjects can receive their data in
a structured, commonly used, machine-readable format.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from our_db import get_cursor

from .audit import AuditAction, get_audit_logger

logger = logging.getLogger(__name__)

# Export format version — increment on schema changes
EXPORT_FORMAT_VERSION = "1.0.0"


def get_holder_data(holder_did: str) -> dict[str, Any]:
    """Retrieve all data associated with a holder (GDPR Article 15).

    Collects beliefs, entities, sessions, patterns, consents, and audit records
    for the given holder DID.

    Args:
        holder_did: DID of the data subject

    Returns:
        Dict with all holder data organized by category
    """
    audit = get_audit_logger()
    result: dict[str, Any] = {
        "holder_did": holder_did,
        "generated_at": datetime.now().isoformat(),
        "categories": {},
    }

    with get_cursor() as cur:
        # Beliefs created by this holder (via source_id or direct content)
        cur.execute(
            """
            SELECT b.* FROM beliefs b
            WHERE b.source_id IN (
                SELECT id FROM sources WHERE name = %s OR url = %s
            )
            OR b.id IN (
                SELECT belief_id FROM belief_entities be
                JOIN entities e ON be.entity_id = e.id
                WHERE e.name = %s AND be.role = 'subject'
            )
            ORDER BY b.created_at DESC
            """,
            (holder_did, holder_did, holder_did),
        )
        beliefs = cur.fetchall()
        result["categories"]["beliefs"] = {
            "count": len(beliefs),
            "records": [_serialize_row(r) for r in beliefs],
        }

        # Entities linked to this holder
        cur.execute(
            "SELECT * FROM entities WHERE name = %s OR %s = ANY(aliases) ORDER BY created_at DESC",
            (holder_did, holder_did),
        )
        entities = cur.fetchall()
        result["categories"]["entities"] = {
            "count": len(entities),
            "records": [_serialize_row(r) for r in entities],
        }

        # Sessions
        cur.execute(
            "SELECT * FROM vkb_sessions WHERE metadata->>'holder_did' = %s ORDER BY started_at DESC",
            (holder_did,),
        )
        sessions = cur.fetchall()
        result["categories"]["sessions"] = {
            "count": len(sessions),
            "records": [_serialize_row(r) for r in sessions],
        }

        # Exchanges from holder sessions
        if sessions:
            session_ids = [str(s["id"]) for s in sessions]
            placeholders = ", ".join(["%s"] * len(session_ids))
            cur.execute(
                f"SELECT * FROM vkb_exchanges WHERE session_id IN ({placeholders}) ORDER BY created_at DESC",
                session_ids,
            )
            exchanges = cur.fetchall()
        else:
            exchanges = []
        result["categories"]["exchanges"] = {
            "count": len(exchanges),
            "records": [_serialize_row(r) for r in exchanges],
        }

        # Patterns
        cur.execute(
            "SELECT * FROM vkb_patterns WHERE metadata->>'holder_did' = %s ORDER BY created_at DESC",
            (holder_did,),
        )
        patterns = cur.fetchall()
        result["categories"]["patterns"] = {
            "count": len(patterns),
            "records": [_serialize_row(r) for r in patterns],
        }

        # Consent records
        cur.execute(
            "SELECT * FROM consent_records WHERE holder_did = %s ORDER BY granted_at DESC",
            (holder_did,),
        )
        consents = cur.fetchall()
        result["categories"]["consents"] = {
            "count": len(consents),
            "records": [_serialize_row(r) for r in consents],
        }

        # Audit log entries for this holder
        cur.execute(
            "SELECT * FROM audit_log WHERE actor_did = %s ORDER BY timestamp DESC LIMIT 1000",
            (holder_did,),
        )
        audit_entries = cur.fetchall()
        result["categories"]["audit_log"] = {
            "count": len(audit_entries),
            "records": [_serialize_row(r) for r in audit_entries],
        }

    # Total counts
    result["total_records"] = sum(
        cat["count"] for cat in result["categories"].values()
    )

    # Log the data access
    audit.log(
        action=AuditAction.DATA_ACCESS,
        resource_type="holder_data",
        resource_id=holder_did,
        details={"total_records": result["total_records"]},
        actor_did=holder_did,
    )

    return result


def export_holder_data(holder_did: str) -> dict[str, Any]:
    """Export all holder data in a portable format (GDPR Article 20).

    Returns data in a structured JSON format with version information
    for import/export interoperability.

    Args:
        holder_did: DID of the data subject

    Returns:
        Dict with export metadata and all holder data
    """
    audit = get_audit_logger()
    data = get_holder_data(holder_did)

    export = {
        "format": "valence-export",
        "version": EXPORT_FORMAT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "holder_did": holder_did,
        "data": data["categories"],
        "metadata": {
            "total_records": data["total_records"],
            "categories": list(data["categories"].keys()),
        },
    }

    # Log the export
    audit.log(
        action=AuditAction.DATA_EXPORT,
        resource_type="holder_data",
        resource_id=holder_did,
        details={
            "format_version": EXPORT_FORMAT_VERSION,
            "total_records": data["total_records"],
        },
        actor_did=holder_did,
    )

    return export


def import_holder_data(data: dict[str, Any]) -> dict[str, Any]:
    """Import holder data from a portable export (GDPR Article 20 inbound).

    Args:
        data: Export data dict (from export_holder_data)

    Returns:
        Dict with import results (counts per category, errors)
    """
    if data.get("format") != "valence-export":
        return {"success": False, "error": "Invalid export format"}

    version = data.get("version", "0.0.0")
    holder_did = data.get("holder_did")
    categories = data.get("data", {})

    results: dict[str, Any] = {
        "success": True,
        "holder_did": holder_did,
        "format_version": version,
        "imported": {},
        "errors": [],
    }

    with get_cursor() as cur:
        # Import beliefs
        beliefs = categories.get("beliefs", {}).get("records", [])
        imported_beliefs = 0
        for belief in beliefs:
            try:
                cur.execute(
                    """
                    INSERT INTO beliefs (content, confidence, domain_path, status, source_type)
                    VALUES (%s, %s, %s, 'active', 'import')
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        belief.get("content", ""),
                        json.dumps(belief.get("confidence", {"overall": 0.5})),
                        belief.get("domain_path", []),
                    ),
                )
                imported_beliefs += 1
            except Exception as e:
                results["errors"].append(f"belief import error: {e}")
        results["imported"]["beliefs"] = imported_beliefs

        # Import consent records
        consents = categories.get("consents", {}).get("records", [])
        imported_consents = 0
        for consent in consents:
            try:
                cur.execute(
                    """
                    INSERT INTO consent_records
                        (holder_did, purpose, scope, granted_at, expires_at, retention_until, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        consent.get("holder_did", holder_did),
                        consent.get("purpose", "data_processing"),
                        consent.get("scope", "all"),
                        consent.get("granted_at", datetime.now().isoformat()),
                        consent.get("expires_at"),
                        consent.get("retention_until"),
                        json.dumps(consent.get("metadata", {})),
                    ),
                )
                imported_consents += 1
            except Exception as e:
                results["errors"].append(f"consent import error: {e}")
        results["imported"]["consents"] = imported_consents

    results["total_imported"] = sum(results["imported"].values())
    return results


def _serialize_row(row: Any) -> dict[str, Any]:
    """Serialize a database row to a JSON-safe dict."""
    if isinstance(row, dict):
        result = {}
        for key, value in row.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif hasattr(value, "hex"):  # UUID
                result[key] = str(value)
            elif isinstance(value, bytes):
                result[key] = value.hex()
            else:
                result[key] = value
        return result
    return dict(row) if hasattr(row, "keys") else {}
