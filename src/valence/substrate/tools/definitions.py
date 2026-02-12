"""Substrate tool definitions with behavioral conditioning.

Contains SUBSTRATE_TOOLS -- the list of all Tool() definitions for the substrate.
"""

from __future__ import annotations

from mcp.types import Tool

SUBSTRATE_TOOLS = [
    Tool(
        name="belief_query",
        description=(
            "Search beliefs by content, domain, or entity. Uses hybrid search (keyword + semantic).\n\n"
            "CRITICAL: You MUST call this BEFORE answering questions about:\n"
            "- Past decisions or discussions\n"
            "- User preferences or values\n"
            "- Technical approaches previously explored\n"
            "- Any topic that may have been discussed before\n\n"
            "Query first, then respond with grounded information. This ensures your "
            "responses are consistent with what has been learned and decided previously.\n\n"
            "Note: Beliefs with revoked consent chains are filtered out by default for privacy."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "domain_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by domain path (e.g., ['tech', 'architecture'])",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Filter by related entity UUID",
                },
                "include_superseded": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include superseded beliefs",
                },
                "include_revoked": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include beliefs with revoked consent chains (requires audit logging)",
                },
                "include_archived": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include archived beliefs in results. Archived beliefs are kept for provenance and reference but excluded from active queries by default.",
                },
                "include_expired": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include beliefs outside their temporal validity window (valid_from/valid_until)",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum results",
                },
                "ranking": {
                    "type": "object",
                    "description": "Configure result ranking weights",
                    "properties": {
                        "semantic_weight": {"type": "number", "default": 0.50, "description": "Weight for semantic relevance (0-1)"},
                        "confidence_weight": {"type": "number", "default": 0.35, "description": "Weight for belief confidence (0-1)"},
                        "recency_weight": {"type": "number", "default": 0.15, "description": "Weight for recency (0-1)"},
                        "explain": {"type": "boolean", "default": False, "description": "Include score breakdown in results"},
                    },
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="belief_create",
        description=(
            "Create a new belief with optional entity links.\n\n"
            "Use PROACTIVELY when:\n"
            "- A decision is made with clear rationale\n"
            "- User expresses a preference or value\n"
            "- A problem is solved with a novel approach\n"
            "- Important factual information is shared\n"
            "- Architectural or design choices are finalized\n\n"
            "Capturing beliefs ensures future conversations have access to this knowledge."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The belief content - should be a clear, factual statement",
                },
                "confidence": {
                    "type": "object",
                    "description": "Confidence dimensions (or single 'overall' value)",
                    "default": {"overall": 0.7},
                },
                "domain_path": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Domain classification (e.g., ['tech', 'python', 'testing'])",
                },
                "source_type": {
                    "type": "string",
                    "enum": [
                        "document",
                        "conversation",
                        "inference",
                        "observation",
                        "user_input",
                    ],
                    "description": "Type of source",
                },
                "source_ref": {
                    "type": "string",
                    "description": "Reference to source (URL, session_id, etc.)",
                },
                "opt_out_federation": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, belief will not be shared via federation (privacy opt-out)",
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string"},
                            "role": {
                                "type": "string",
                                "enum": ["subject", "object", "context"],
                            },
                        },
                        "required": ["name"],
                    },
                    "description": "Entities to link (will be created if not exist)",
                },
                "visibility": {
                    "type": "string",
                    "enum": ["private", "federated", "public"],
                    "default": "private",
                    "description": "Visibility level for the belief",
                },
                "sharing_intent": {
                    "type": "string",
                    "enum": ["know_me", "work_with_me", "learn_from_me", "use_this"],
                    "description": "Optional sharing intent — generates a SharePolicy stored with the belief",
                },
            },
            "required": ["content"],
        },
    ),
    Tool(
        name="belief_supersede",
        description=(
            "Replace an old belief with a new one, maintaining history.\n\n"
            "Use when:\n"
            "- Information needs to be updated or corrected\n"
            "- A previous decision has been revised\n"
            "- More accurate information is now available\n\n"
            "This maintains the full history chain so we can understand how knowledge evolved."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "old_belief_id": {
                    "type": "string",
                    "description": "UUID of belief to supersede",
                },
                "new_content": {
                    "type": "string",
                    "description": "Updated belief content",
                },
                "reason": {
                    "type": "string",
                    "description": "Why this belief is being superseded",
                },
                "confidence": {
                    "type": "object",
                    "description": "Confidence for new belief",
                },
            },
            "required": ["old_belief_id", "new_content", "reason"],
        },
    ),
    Tool(
        name="belief_get",
        description=(
            "Get a single belief by ID with full details.\n\n"
            "Use to examine a specific belief's content, history, and related tensions "
            "when you need more context than what belief_query provides."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief",
                },
                "include_history": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include supersession chain",
                },
                "include_tensions": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include related tensions",
                },
            },
            "required": ["belief_id"],
        },
    ),
    Tool(
        name="entity_get",
        description=(
            "Get entity details with optional beliefs.\n\n"
            "Use when you need comprehensive information about a person, tool, "
            "concept, or organization that has been discussed before."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "UUID of the entity",
                },
                "include_beliefs": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include related beliefs",
                },
                "belief_limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Max beliefs to include",
                },
            },
            "required": ["entity_id"],
        },
    ),
    Tool(
        name="entity_search",
        description=(
            "Find entities by name or type.\n\n"
            "Use to discover what's known about specific people, tools, projects, "
            "or concepts before making statements about them."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (matches name and aliases)",
                },
                "type": {
                    "type": "string",
                    "enum": [
                        "person",
                        "organization",
                        "tool",
                        "concept",
                        "project",
                        "location",
                        "service",
                    ],
                    "description": "Filter by entity type",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="tension_list",
        description=(
            "List contradictions/tensions between beliefs.\n\n"
            "Review tensions periodically to identify knowledge that needs "
            "reconciliation or clarification."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["detected", "investigating", "resolved", "accepted"],
                    "description": "Filter by status",
                },
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Minimum severity",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Tensions involving this entity",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                },
            },
        },
    ),
    Tool(
        name="tension_resolve",
        description=("Mark a tension as resolved with explanation.\n\nUse when you've determined how to reconcile conflicting beliefs."),
        inputSchema={
            "type": "object",
            "properties": {
                "tension_id": {
                    "type": "string",
                    "description": "UUID of the tension",
                },
                "resolution": {
                    "type": "string",
                    "description": "How the tension was resolved",
                },
                "action": {
                    "type": "string",
                    "enum": ["supersede_a", "supersede_b", "keep_both", "archive_both"],
                    "description": "What to do with the beliefs",
                },
            },
            "required": ["tension_id", "resolution", "action"],
        },
    ),
    Tool(
        name="belief_corroboration",
        description=(
            "Get corroboration details for a belief - how many independent sources confirm it.\n\n"
            "Use when:\n"
            "- You need to assess how well-supported a belief is\n"
            "- You want to see which federation peers have confirmed similar knowledge\n"
            "- You're evaluating the reliability of a belief\n\n"
            "Higher corroboration count indicates multiple independent sources agree."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief to check corroboration for",
                },
            },
            "required": ["belief_id"],
        },
    ),
    Tool(
        name="belief_search",
        description=(
            "Semantic search for beliefs using vector embeddings.\n\n"
            "Best for finding conceptually related beliefs even with different wording. "
            "Use this instead of belief_query when:\n"
            "- The exact keywords may not match but the concept is the same\n"
            "- You want to find beliefs that are semantically similar\n"
            "- You need to discover related knowledge that uses different terminology\n\n"
            "Requires embeddings to be enabled (OPENAI_API_KEY)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query to find semantically similar beliefs",
                },
                "min_similarity": {
                    "type": "number",
                    "default": 0.5,
                    "description": "Minimum similarity threshold (0-1)",
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Filter by minimum overall confidence",
                },
                "domain_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by domain path",
                },
                "include_archived": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include archived beliefs in results. Archived beliefs are kept for provenance and reference but excluded from active queries by default.",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum results",
                },
                "ranking": {
                    "type": "object",
                    "description": "Configure result ranking weights",
                    "properties": {
                        "semantic_weight": {"type": "number", "default": 0.50, "description": "Weight for semantic similarity (0-1)"},
                        "confidence_weight": {"type": "number", "default": 0.35, "description": "Weight for belief confidence (0-1)"},
                        "recency_weight": {"type": "number", "default": 0.15, "description": "Weight for recency (0-1)"},
                        "explain": {"type": "boolean", "default": False, "description": "Include score breakdown in results"},
                    },
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="trust_check",
        description=(
            "Check trust levels for entities or federation nodes on a specific topic/domain.\n\n"
            "Use when:\n"
            "- You need to assess who is authoritative on a topic\n"
            "- You want to know which federation peers are trusted\n"
            "- You're evaluating the reliability of information sources\n\n"
            "Returns entities with high-confidence beliefs in the domain and trusted federation nodes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic or domain to check trust for",
                },
                "entity_name": {
                    "type": "string",
                    "description": "Specific entity to check trust for",
                },
                "include_federated": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include federated node trust",
                },
                "min_trust": {
                    "type": "number",
                    "default": 0.3,
                    "description": "Minimum trust threshold",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                },
                "domain": {
                    "type": "string",
                    "description": "Domain scope for trust scoring (e.g., 'tech', 'science'). "
                    "Uses domain-specific trust from node_trust with fallback to overall trust.",
                },
            },
            "required": ["topic"],
        },
    ),
    Tool(
        name="confidence_explain",
        description=(
            "Explain why a belief has a particular confidence score, showing all contributing dimensions.\n\n"
            "Use when:\n"
            "- You need to understand why a belief is rated at a certain confidence\n"
            "- You want to identify which dimensions are weak and need improvement\n"
            "- You're helping the user understand the reliability of stored knowledge\n\n"
            "Returns a breakdown of all confidence dimensions with weights and recommendations."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief to explain",
                },
            },
            "required": ["belief_id"],
        },
    ),
    Tool(
        name="belief_share",
        description=(
            "Share a belief with a specific person via their DID.\n\n"
            "Use when:\n"
            "- A user wants to share knowledge with a trusted person\n"
            "- Collaborative work requires sharing specific beliefs\n"
            "- Knowledge should be made available to someone specific\n\n"
            "Creates a consent chain and share record. The intent parameter controls "
            "how the share behaves (know_me=private 1:1, work_with_me=bounded group, "
            "learn_from_me=cascading, use_this=public)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief to share",
                },
                "recipient_did": {
                    "type": "string",
                    "description": "DID of the person to share with",
                },
                "intent": {
                    "type": "string",
                    "enum": ["know_me", "work_with_me", "learn_from_me", "use_this"],
                    "default": "know_me",
                    "description": "Sharing intent (controls policy and enforcement)",
                },
                "max_hops": {
                    "type": "integer",
                    "description": "Override default max reshare hops for the intent",
                },
                "expires_at": {
                    "type": "string",
                    "description": "ISO 8601 expiration timestamp for the share",
                },
            },
            "required": ["belief_id", "recipient_did"],
        },
    ),
    Tool(
        name="belief_shares_list",
        description=(
            "List shares — either outgoing (beliefs you've shared) or incoming (shared with you).\n\n"
            "Use to review what has been shared and with whom."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["outgoing", "incoming"],
                    "default": "outgoing",
                    "description": "Whether to list shares you created or shares sent to you",
                },
                "belief_id": {
                    "type": "string",
                    "description": "Filter shares to a specific belief UUID",
                },
                "include_revoked": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include revoked shares in results",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum results",
                },
            },
        },
    ),
    Tool(
        name="belief_share_revoke",
        description=(
            "Revoke a previously created share.\n\n"
            "Use when:\n"
            "- A share should no longer be active\n"
            "- Trust has changed and access should be removed\n"
            "- The shared information is no longer valid\n\n"
            "Marks the consent chain as revoked. The recipient will no longer have access."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "share_id": {
                    "type": "string",
                    "description": "UUID of the share to revoke",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional reason for revocation",
                },
            },
            "required": ["share_id"],
        },
    ),
    # =========================================================================
    # Verification Protocol Tools
    # =========================================================================
    Tool(
        name="verification_submit",
        description=(
            "Submit a verification for a belief. Verifiers stake reputation to validate or challenge beliefs.\n\n"
            "Use when:\n"
            "- You want to confirm or contradict a belief with evidence\n"
            "- You have new evidence about a claim\n"
            "- You want to earn reputation by verifying knowledge\n\n"
            "Finding contradictions earns higher rewards than confirmations. "
            "Stake is locked during the verification window."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief to verify",
                },
                "verifier_id": {
                    "type": "string",
                    "description": "DID of the verifier (e.g., did:valence:bob)",
                },
                "result": {
                    "type": "string",
                    "enum": ["confirmed", "contradicted", "uncertain", "partial"],
                    "description": "Verification result",
                },
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["external", "belief_reference", "observation", "derivation"]},
                            "relevance": {"type": "number", "description": "Relevance score 0-1"},
                            "contribution": {"type": "string", "enum": ["supports", "contradicts", "neutral"]},
                        },
                    },
                    "description": "Evidence supporting the verification",
                },
                "stake_amount": {
                    "type": "number",
                    "description": "Amount of reputation to stake (higher stakes = higher potential reward)",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Optional reasoning for the verification",
                },
                "result_details": {
                    "type": "object",
                    "description": "Optional details for partial results (accuracy_estimate, confirmed_aspects, contradicted_aspects)",
                },
            },
            "required": ["belief_id", "verifier_id", "result", "evidence", "stake_amount"],
        },
    ),
    Tool(
        name="verification_accept",
        description=(
            "Accept a pending verification after the validation window.\n\n"
            "This triggers reputation updates for both the verifier and the belief holder. "
            "Confirmations earn moderate rewards; contradictions earn higher rewards."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "verification_id": {
                    "type": "string",
                    "description": "UUID of the verification to accept",
                },
            },
            "required": ["verification_id"],
        },
    ),
    Tool(
        name="verification_get",
        description="Get details of a specific verification by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "verification_id": {
                    "type": "string",
                    "description": "UUID of the verification",
                },
            },
            "required": ["verification_id"],
        },
    ),
    Tool(
        name="verification_list",
        description=(
            "List all verifications for a specific belief.\n\n"
            "Use to see what verifiers have said about a belief — "
            "whether it has been confirmed, contradicted, or disputed."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief",
                },
            },
            "required": ["belief_id"],
        },
    ),
    Tool(
        name="verification_summary",
        description=(
            "Get a summary of verification activity for a belief.\n\n"
            "Returns counts by result type, total stake, and the current consensus result "
            "weighted by verifier reputation and stake amount."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief",
                },
            },
            "required": ["belief_id"],
        },
    ),
    Tool(
        name="dispute_submit",
        description=(
            "Submit a dispute against a verification.\n\n"
            "Use when:\n"
            "- You believe a verification result is incorrect\n"
            "- You have counter-evidence to challenge a verification\n"
            "- A verification was made in bad faith\n\n"
            "Disputes require staking reputation. Winning a dispute earns rewards; "
            "losing forfeits the stake."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "verification_id": {
                    "type": "string",
                    "description": "UUID of the verification to dispute",
                },
                "disputer_id": {
                    "type": "string",
                    "description": "DID of the disputer",
                },
                "counter_evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["external", "belief_reference", "observation", "derivation"]},
                            "relevance": {"type": "number"},
                            "contribution": {"type": "string", "enum": ["supports", "contradicts", "neutral"]},
                        },
                    },
                    "description": "Counter-evidence for the dispute",
                },
                "stake_amount": {
                    "type": "number",
                    "description": "Amount of reputation to stake on the dispute",
                },
                "dispute_type": {
                    "type": "string",
                    "enum": ["new_evidence", "methodology", "scope", "bias"],
                    "description": "Type of dispute",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Reasoning for the dispute",
                },
                "proposed_result": {
                    "type": "string",
                    "enum": ["confirmed", "contradicted", "uncertain", "partial"],
                    "description": "What the correct result should be (optional)",
                },
            },
            "required": ["verification_id", "disputer_id", "counter_evidence", "stake_amount", "dispute_type", "reasoning"],
        },
    ),
    Tool(
        name="dispute_resolve",
        description=(
            "Resolve a pending dispute with an outcome.\n\n"
            "Outcomes: upheld (original verifier wins), overturned (disputer wins), "
            "modified (partial adjustment), dismissed (frivolous dispute penalty)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "dispute_id": {
                    "type": "string",
                    "description": "UUID of the dispute to resolve",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["upheld", "overturned", "modified", "dismissed"],
                    "description": "Resolution outcome",
                },
                "resolution_reasoning": {
                    "type": "string",
                    "description": "Explanation for the resolution",
                },
                "resolution_method": {
                    "type": "string",
                    "enum": ["automatic", "peer_review", "arbitration"],
                    "default": "automatic",
                    "description": "How the dispute was resolved",
                },
            },
            "required": ["dispute_id", "outcome", "resolution_reasoning"],
        },
    ),
    Tool(
        name="dispute_get",
        description="Get details of a specific dispute by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "dispute_id": {
                    "type": "string",
                    "description": "UUID of the dispute",
                },
            },
            "required": ["dispute_id"],
        },
    ),
    Tool(
        name="reputation_get",
        description=(
            "Get the reputation score for an identity.\n\n"
            "Returns overall reputation, domain-specific scores, verification count, "
            "discrepancy finds, and current stake at risk."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "identity_id": {
                    "type": "string",
                    "description": "DID of the identity (e.g., did:valence:alice)",
                },
            },
            "required": ["identity_id"],
        },
    ),
    Tool(
        name="reputation_events",
        description=(
            "Get reputation event history for an identity.\n\n"
            "Shows how reputation changed over time — what actions caused "
            "increases or decreases."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "identity_id": {
                    "type": "string",
                    "description": "DID of the identity",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum events to return",
                },
            },
            "required": ["identity_id"],
        },
    ),
    Tool(
        name="bounty_get",
        description=(
            "Get the discrepancy bounty for a belief.\n\n"
            "High-confidence beliefs have bounties for finding contradictions. "
            "The bounty amount scales with belief confidence."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief",
                },
            },
            "required": ["belief_id"],
        },
    ),
    Tool(
        name="bounty_list",
        description=(
            "List available discrepancy bounties.\n\n"
            "Shows beliefs with active bounties for finding contradictions. "
            "Higher bounties indicate more valuable verification targets."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "unclaimed_only": {
                    "type": "boolean",
                    "default": True,
                    "description": "Only show unclaimed bounties",
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum bounties to return",
                },
            },
        },
    ),
    # =========================================================================
    # Incentive System Tools
    # =========================================================================
    Tool(
        name="calibration_run",
        description=(
            "Run calibration scoring for an identity.\n\n"
            "Calculates the Brier score for the period — how well-calibrated the "
            "identity's confidence claims are vs actual verification outcomes. "
            "Well-calibrated agents earn bonuses; poorly calibrated face penalties."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "identity_id": {
                    "type": "string",
                    "description": "DID of the identity to score",
                },
                "period_start": {
                    "type": "string",
                    "description": "Start of period (YYYY-MM-DD). Defaults to last month.",
                },
            },
            "required": ["identity_id"],
        },
    ),
    Tool(
        name="calibration_history",
        description="Get calibration score history for an identity.",
        inputSchema={
            "type": "object",
            "properties": {
                "identity_id": {
                    "type": "string",
                    "description": "DID of the identity",
                },
                "limit": {
                    "type": "integer",
                    "default": 12,
                    "description": "Maximum snapshots to return",
                },
            },
            "required": ["identity_id"],
        },
    ),
    Tool(
        name="rewards_pending",
        description=(
            "Get pending (unclaimed) rewards for an identity.\n\n"
            "Shows earned reputation rewards that haven't been claimed yet. "
            "Rewards come from verifications, calibration bonuses, bounties, etc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "identity_id": {
                    "type": "string",
                    "description": "DID of the identity",
                },
            },
            "required": ["identity_id"],
        },
    ),
    Tool(
        name="reward_claim",
        description=(
            "Claim a single pending reward, applying it to reputation.\n\n"
            "Subject to velocity limits (daily/weekly gain caps)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "reward_id": {
                    "type": "string",
                    "description": "UUID of the reward to claim",
                },
            },
            "required": ["reward_id"],
        },
    ),
    Tool(
        name="rewards_claim_all",
        description=(
            "Claim all pending rewards for an identity.\n\n"
            "Claims rewards in order until velocity limits are reached."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "identity_id": {
                    "type": "string",
                    "description": "DID of the identity",
                },
            },
            "required": ["identity_id"],
        },
    ),
    Tool(
        name="transfer_history",
        description=(
            "Get transfer history for an identity.\n\n"
            "Shows system-initiated reputation movements: stake forfeitures, "
            "bounty payouts, dispute settlements, calibration bonuses."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "identity_id": {
                    "type": "string",
                    "description": "DID of the identity",
                },
                "direction": {
                    "type": "string",
                    "enum": ["both", "incoming", "outgoing"],
                    "default": "both",
                    "description": "Filter by transfer direction",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Maximum transfers to return",
                },
            },
            "required": ["identity_id"],
        },
    ),
    Tool(
        name="velocity_status",
        description=(
            "Get current velocity status for an identity.\n\n"
            "Shows daily/weekly gain tracking and remaining capacity before hitting limits. "
            "Velocity limits prevent gaming through rapid reputation farming."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "identity_id": {
                    "type": "string",
                    "description": "DID of the identity",
                },
            },
            "required": ["identity_id"],
        },
    ),
    # =========================================================================
    # Consensus Mechanism Tools
    # =========================================================================
    Tool(
        name="consensus_status",
        description=(
            "Get the consensus status for a belief.\n\n"
            "Shows current trust layer (L1-L4), corroboration count, finality level, "
            "and challenge history. Beliefs start at L1 (personal) and can be elevated "
            "through independent corroboration."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief",
                },
            },
            "required": ["belief_id"],
        },
    ),
    Tool(
        name="corroboration_submit",
        description=(
            "Submit a corroboration between two beliefs.\n\n"
            "Corroboration is independent verification — two beliefs reaching the same "
            "conclusion through different evidence. Requires semantic similarity >= 0.85. "
            "Independence is calculated from evidence source overlap."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "primary_belief_id": {
                    "type": "string",
                    "description": "UUID of the belief being corroborated",
                },
                "corroborating_belief_id": {
                    "type": "string",
                    "description": "UUID of the supporting belief",
                },
                "primary_holder": {
                    "type": "string",
                    "description": "DID of the primary belief holder",
                },
                "corroborator": {
                    "type": "string",
                    "description": "DID of the corroborator",
                },
                "semantic_similarity": {
                    "type": "number",
                    "description": "How similar the claims are (must be >= 0.85)",
                },
                "evidence_sources_a": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Evidence sources for primary belief",
                },
                "evidence_sources_b": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Evidence sources for corroborating belief",
                },
                "corroborator_reputation": {
                    "type": "number",
                    "default": 0.5,
                    "description": "Reputation of the corroborator (affects weight)",
                },
            },
            "required": ["primary_belief_id", "corroborating_belief_id", "primary_holder", "corroborator", "semantic_similarity"],
        },
    ),
    Tool(
        name="corroboration_list",
        description="List corroborations for a belief.",
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief",
                },
            },
            "required": ["belief_id"],
        },
    ),
    Tool(
        name="challenge_submit",
        description=(
            "Submit a challenge to a belief's consensus status.\n\n"
            "Challenges contest a belief's trust layer. Cannot challenge L1 (personal) beliefs. "
            "If upheld, the belief is demoted to a lower layer."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief to challenge",
                },
                "challenger_id": {
                    "type": "string",
                    "description": "DID of the challenger",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Reasoning for the challenge",
                },
                "evidence": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Supporting evidence for the challenge",
                },
                "stake_amount": {
                    "type": "number",
                    "default": 0,
                    "description": "Reputation staked on the challenge",
                },
            },
            "required": ["belief_id", "challenger_id", "reasoning"],
        },
    ),
    Tool(
        name="challenge_resolve",
        description=(
            "Resolve a pending challenge.\n\n"
            "If upheld, the belief is demoted. If rejected, the challenger loses stake."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "challenge_id": {
                    "type": "string",
                    "description": "UUID of the challenge",
                },
                "upheld": {
                    "type": "boolean",
                    "description": "Whether the challenge is upheld (true) or rejected (false)",
                },
                "resolution_reasoning": {
                    "type": "string",
                    "description": "Explanation for the resolution",
                },
            },
            "required": ["challenge_id", "upheld", "resolution_reasoning"],
        },
    ),
    Tool(
        name="challenge_get",
        description="Get details of a specific challenge by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "challenge_id": {
                    "type": "string",
                    "description": "UUID of the challenge",
                },
            },
            "required": ["challenge_id"],
        },
    ),
    Tool(
        name="challenges_list",
        description="List all challenges for a belief.",
        inputSchema={
            "type": "object",
            "properties": {
                "belief_id": {
                    "type": "string",
                    "description": "UUID of the belief",
                },
            },
            "required": ["belief_id"],
        },
    ),
    # ── Resilient Storage ────────────────────────────────────────────────
    Tool(
        name="backup_create",
        description=(
            "Create a backup of beliefs.\n\n"
            "Selects beliefs, serializes, and creates erasure-coded shards stored locally. "
            "Supports four redundancy levels: minimal (3-of-5), personal (5-of-8), "
            "federation (8-of-12), paranoid (12-of-20)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "redundancy": {
                    "type": "string",
                    "description": "Redundancy level: minimal, personal, federation, or paranoid",
                    "default": "personal",
                },
                "domain_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only back up beliefs in these domains",
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Only back up beliefs with at least this overall confidence",
                },
                "encrypt": {
                    "type": "boolean",
                    "description": "Whether to encrypt the backup payload",
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="backup_verify",
        description=(
            "Verify integrity of a backup set.\n\n"
            "Checks each shard's checksum against the stored value and reports "
            "whether the backup can be recovered."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "backup_set_id": {
                    "type": "string",
                    "description": "UUID of the backup set to verify",
                },
            },
            "required": ["backup_set_id"],
        },
    ),
    Tool(
        name="backup_list",
        description="List backup sets ordered by creation date.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of backups to return",
                    "default": 20,
                },
            },
        },
    ),
    Tool(
        name="backup_get",
        description="Get details of a specific backup set by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "backup_set_id": {
                    "type": "string",
                    "description": "UUID of the backup set",
                },
            },
            "required": ["backup_set_id"],
        },
    ),
]
