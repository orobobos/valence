"""Trust graph module for Valence privacy.

Implements multi-dimensional trust edges between DIDs with database storage.
Trust has four dimensions:
- competence: Ability to perform tasks correctly
- integrity: Honesty and consistency
- confidentiality: Ability to keep secrets
- judgment: Ability to evaluate others (affects delegated trust)

The judgment dimension is special: it affects how much weight we give to
someone's trust recommendations. Low judgment means their trust in others
is weighted less in transitive trust calculations.

Trust Decay:
Trust can decay over time if not refreshed. This models the natural erosion
of trust when relationships aren't maintained. Decay is configurable via:
- decay_rate: Rate of decay per day (0.0 = no decay)
- decay_model: LINEAR (constant loss) or EXPONENTIAL (percentage loss)
- last_refreshed: When trust was last confirmed/refreshed
"""

from __future__ import annotations

# Decay models and constants
from .decay import CLOCK_SKEW_TOLERANCE, DecayModel

# Trust edge definition
from .edges import TrustEdge, TrustEdge4D

# Federation trust
from .federation import (
    FEDERATION_PREFIX,
    FederationMembershipRegistry,
    FederationTrustEdge,
    get_did_federation,
    get_effective_trust_with_federation,
    get_federation_registry,
    get_federation_trust,
    register_federation_member,
    revoke_federation_trust,
    set_federation_trust,
    unregister_federation_member,
)

# Trust graph service and convenience functions
from .graph import (
    TrustService,
    compute_delegated_trust_from_service,
    get_trust,
    get_trust_service,
    grant_trust,
    list_trusted,
    list_trusters,
    revoke_trust,
)

# Trust propagation algorithms
from .propagation import compute_delegated_trust, compute_transitive_trust

# Trust storage
from .storage import TrustGraphStore, get_trust_graph_store

__all__ = [
    # Decay
    "CLOCK_SKEW_TOLERANCE",
    "DecayModel",
    # Edges
    "TrustEdge",
    "TrustEdge4D",
    # Propagation
    "compute_delegated_trust",
    "compute_transitive_trust",
    # Storage
    "TrustGraphStore",
    "get_trust_graph_store",
    # Graph service
    "TrustService",
    "get_trust_service",
    "grant_trust",
    "revoke_trust",
    "get_trust",
    "list_trusted",
    "list_trusters",
    "compute_delegated_trust_from_service",
    # Federation
    "FEDERATION_PREFIX",
    "FederationTrustEdge",
    "FederationMembershipRegistry",
    "get_federation_registry",
    "set_federation_trust",
    "get_federation_trust",
    "revoke_federation_trust",
    "get_effective_trust_with_federation",
    "register_federation_member",
    "unregister_federation_member",
    "get_did_federation",
]
