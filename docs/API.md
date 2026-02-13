# API Reference

Valence exposes two interfaces: **MCP tools** (JSON-RPC over stdio or HTTP) and **REST endpoints** (HTTP).

For the full OpenAPI specification, see [openapi.yaml](openapi.yaml).

## MCP Tools (58 total)

All MCP tools return `{"success": true/false, ...}`. Tools are served via either stdio (`python -m valence.mcp_server`) or HTTP (`valence-server` at `/api/v1/mcp`).

### Knowledge Base — Beliefs (9 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `belief_query` | `query` | Search beliefs by content, domain, or entity. Supports `ranking` param with configurable weights. |
| `belief_create` | `content` | Create a new belief with optional entity links, confidence, domain_path. |
| `belief_supersede` | `old_belief_id`, `new_content`, `reason` | Replace a belief maintaining full history chain. |
| `belief_get` | `belief_id` | Get a single belief by UUID. Options: `include_history`, `include_tensions`. |
| `belief_search` | `query` | Semantic search via vector embeddings. Options: `min_similarity`, `limit`, `ranking`. |
| `belief_share` | `belief_id`, `recipient_did` | Share a belief with a specific DID. |
| `belief_shares_list` | — | List outgoing or incoming shares. Options: `direction`, `status`. |
| `belief_share_revoke` | `share_id` | Revoke a previously created share. |
| `belief_corroboration` | `belief_id` | Get corroboration count and sources for a belief. |

### Entities (2 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `entity_get` | `entity_id` | Get entity details. Options: `include_beliefs`, `belief_limit`. |
| `entity_search` | `query` | Find entities by name or type. Options: `type`, `limit`. |

### Tensions (2 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `tension_list` | — | List contradictions. Filters: `status`, `severity`, `entity_id`, `limit`. |
| `tension_resolve` | `tension_id`, `resolution`, `action` | Resolve a tension. Actions: `supersede_a`, `supersede_b`, `keep_both`, `archive_both`. |

### Confidence & Trust (2 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `confidence_explain` | `belief_id` | Breakdown of confidence dimensions with weights and recommendations. |
| `trust_check` | `topic` | Check trust levels for entities/nodes on a topic. Options: `entity_name`, `include_federated`, `min_trust`, `limit`. |

### Verification Protocol (5 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `verification_submit` | `belief_id`, `verifier_id`, `result`, `evidence`, `stake_amount` | Submit a verification with evidence and stake. |
| `verification_accept` | `verification_id` | Accept a pending verification after validation window. |
| `verification_get` | `verification_id` | Get verification details by ID. |
| `verification_list` | `belief_id` | List all verifications for a belief. |
| `verification_summary` | `belief_id` | Aggregated verification activity summary. |

### Disputes (3 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `dispute_submit` | `verification_id`, `disputer_id`, `counter_evidence`, `stake_amount`, `dispute_type`, `reasoning` | Submit a dispute against a verification. |
| `dispute_resolve` | `dispute_id`, `outcome`, `resolution_reasoning` | Resolve a dispute. Outcomes: UPHELD, OVERTURNED, MODIFIED, DISMISSED. |
| `dispute_get` | `dispute_id` | Get dispute details by ID. |

### Reputation (2 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `reputation_get` | `identity_id` | Get reputation score (overall + by domain). |
| `reputation_events` | `identity_id` | Get reputation event history. |

### Bounties (2 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `bounty_get` | `belief_id` | Get the discrepancy bounty for a belief. |
| `bounty_list` | — | List available bounties. Options: `min_amount`, `domain`, `limit`. |

### Calibration & Rewards (6 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `calibration_run` | `identity_id` | Run Brier score calibration for an identity. |
| `calibration_history` | `identity_id` | Get calibration score history. |
| `rewards_pending` | `identity_id` | Get unclaimed rewards. |
| `reward_claim` | `reward_id` | Claim a single reward. |
| `rewards_claim_all` | `identity_id` | Claim all pending rewards. |
| `transfer_history` | `identity_id` | Get transfer history. |
| `velocity_status` | `identity_id` | Current velocity limits status. |

### Consensus Mechanism (7 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `consensus_status` | `belief_id` | Get consensus status (L1-L4 layer, corroboration count). |
| `corroboration_submit` | `primary_belief_id`, `corroborating_belief_id`, `primary_holder`, `corroborator`, `semantic_similarity` | Submit a corroboration between beliefs. |
| `corroboration_list` | `belief_id` | List corroborations for a belief. |
| `challenge_submit` | `belief_id`, `challenger_id`, `reasoning` | Challenge a belief's consensus status. |
| `challenge_resolve` | `challenge_id`, `upheld`, `resolution_reasoning` | Resolve a challenge. |
| `challenge_get` | `challenge_id` | Get challenge details. |
| `challenges_list` | `belief_id` | List challenges for a belief. |

### Backup & Resilience (4 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `backup_create` | — | Create a backup. Options: `domain`, `redundancy`, `encrypt`. |
| `backup_verify` | `backup_set_id` | Verify backup integrity via Merkle root. |
| `backup_list` | — | List backup sets. Options: `limit`. |
| `backup_get` | `backup_set_id` | Get backup set details. |

### Session Tracking (5 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `session_start` | `platform` | Begin a new session. Options: `project_context`, `external_room_id`, `metadata`. |
| `session_end` | `session_id` | Close session with summary and themes. |
| `session_get` | `session_id` | Get session details. Options: `include_exchanges`, `exchange_limit`. |
| `session_list` | — | List sessions. Filters: `status`, `platform`, `project_context`, `limit`. |
| `session_find_by_room` | `external_room_id` | Find active session by room ID. |

### Exchanges (2 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `exchange_add` | `session_id`, `role`, `content` | Record a conversation turn. |
| `exchange_list` | `session_id` | Get exchanges from a session. Options: `limit`, `offset`. |

### Patterns (4 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `pattern_record` | `type`, `description` | Record a behavioral pattern. Options: `confidence`, `evidence`. |
| `pattern_reinforce` | `pattern_id` | Strengthen a pattern with new evidence. |
| `pattern_list` | — | List patterns. Filters: `type`, `status`, `min_confidence`, `limit`. |
| `pattern_search` | `query` | Search patterns by description. |

### Insights (2 tools)

| Tool | Required Params | Description |
|------|----------------|-------------|
| `insight_extract` | `session_id`, `content` | Extract insight from session, create belief. Options: `domain_path`, `entities`, `confidence`. |
| `insight_list` | `session_id` | List insights from a session. |

## REST Endpoints

### Discovery

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Health check |
| `GET` | `/.well-known/oauth-protected-resource` | None | RFC 9728 resource metadata |
| `GET` | `/.well-known/oauth-authorization-server` | None | RFC 8414 server metadata |

### MCP

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/mcp` | Bearer / OAuth | JSON-RPC 2.0 MCP endpoint |

### OAuth 2.1

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/oauth/register` | None | Dynamic client registration (RFC 7591) |
| `GET` | `/api/v1/oauth/authorize` | None | Authorization endpoint (renders login form) |
| `POST` | `/api/v1/oauth/authorize` | None | Process authorization (form submit) |
| `POST` | `/api/v1/oauth/token` | None | Token endpoint (code exchange, refresh) |
| `POST` | `/api/v1/oauth/revoke` | None | Token revocation |

### Compliance (GDPR)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `DELETE` | `/api/v1/compliance/delete` | Bearer | Right to erasure (Article 17) |
| `GET` | `/api/v1/compliance/access` | Bearer | Data access (Article 15) |
| `GET` | `/api/v1/compliance/export` | Bearer | Data portability/export (Article 20) |
| `POST` | `/api/v1/compliance/import` | Bearer | Data import |
| `GET` | `/api/v1/compliance/deletion-verification` | Bearer | Verify deletion completeness |

### Federation

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/federation/node-info` | Optional | Node metadata |
| `POST` | `/api/v1/federation/sync` | DID Auth | Sync beliefs with peer |
| `GET` | `/api/v1/federation/peers` | Bearer | List known peers |

### Sharing

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/shares` | Bearer | Create a share |
| `GET` | `/api/v1/shares` | Bearer | List shares |
| `DELETE` | `/api/v1/shares/{share_id}` | Bearer | Revoke a share |
| `GET` | `/api/v1/shares/incoming` | Bearer | List incoming shares |

### Notifications

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/notifications` | Bearer | List notifications |
| `PUT` | `/api/v1/notifications/{id}/read` | Bearer | Mark notification as read |
