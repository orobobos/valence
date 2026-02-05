"""In-memory storage for federation groups (MVP)."""

from uuid import UUID

from .federation import FederationGroup

# Simple in-memory storage for federation groups
_federation_group_store: dict[UUID, FederationGroup] = {}
_federation_to_group: dict[UUID, UUID] = {}  # federation_id -> group_id


def store_federation_group(group: FederationGroup) -> None:
    """Store a federation group in the in-memory store."""
    _federation_group_store[group.id] = group
    _federation_to_group[group.federation_id] = group.id


def get_federation_group(group_id: UUID) -> FederationGroup | None:
    """Get a federation group by ID."""
    return _federation_group_store.get(group_id)


def get_group_by_federation_id(federation_id: UUID) -> FederationGroup | None:
    """Get the group for a federation."""
    group_id = _federation_to_group.get(federation_id)
    if group_id:
        return _federation_group_store.get(group_id)
    return None


def delete_federation_group(group_id: UUID) -> bool:
    """Delete a federation group."""
    group = _federation_group_store.get(group_id)
    if group:
        del _federation_group_store[group_id]
        if group.federation_id in _federation_to_group:
            del _federation_to_group[group.federation_id]
        return True
    return False


def list_federation_groups() -> list[FederationGroup]:
    """List all federation groups."""
    return list(_federation_group_store.values())


def clear_federation_store() -> None:
    """Clear the in-memory store (for testing)."""
    _federation_group_store.clear()
    _federation_to_group.clear()
