# Implementation Status

Mapping of every spec component to its current implementation state.

Last updated: 2026-02-11

## Component Status

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| Belief Schema | Complete | `our_models`, `substrate/tools/beliefs.py` | 6D confidence, temporal validity, supersession chains |
| Confidence Vectors | Complete | `our_confidence`, `substrate/tools/confidence.py` | Dimensional scoring, geometric mean, explanations |
| Query Protocol | Complete | `substrate/tools/beliefs.py`, `core/ranking.py` | Hybrid search (keyword + semantic), configurable ranking |
| Trust Graph | Complete | `our_privacy`, `substrate/tools/trust.py` | Multi-dimensional trust, entity trust scoring |
| Entity Model | Complete | `substrate/tools/entities.py` | Case-insensitive dedup, aliases, type filtering |
| Tensions | Complete | `substrate/tools/tensions.py` | Detection, resolution, severity levels |
| Temporal Validity | Complete | `core/temporal.py` | Validity ranges, freshness decay, supersession chains |
| Sharing | Complete | `substrate/tools/sharing.py` | DID-based sharing, trust-gated visibility |
| Verification Protocol | Complete | `core/verification/`, `substrate/tools/verification.py` | Submit, accept, dispute, resolve lifecycle |
| Incentive System | Complete | `core/incentives.py`, `substrate/tools/incentives.py` | Reputation, stakes, rewards, calibration (Brier), velocity limits |
| Consensus Mechanism | Complete | `core/consensus.py`, `substrate/tools/consensus.py` | L1-L4 layers, corroboration, challenges, independence scoring |
| Resilient Storage | Complete | `core/backup.py`, `substrate/tools/backup.py` | Erasure coding, encryption, integrity verification |
| Federation | Complete | `our_federation` (brick) | P2P sync, consent, trust propagation, groups |
| Identity | Complete | `our_identity` (brick) | DID-based, Ed25519, key management |
| Privacy | Complete | `our_privacy` (brick) | Trust graph, capabilities, audit, watermarking |
| Compliance | Complete | `compliance/`, `server/compliance_endpoints.py` | Consent, GDPR access/export/import, audit logging, deletion |
| Session Tracking | Complete | `vkb/tools/` | Sessions, exchanges, patterns, insights |
| HTTP MCP Server | Complete | `server/` | OAuth 2.1 + PKCE, Bearer tokens, rate limiting |
| CLI | Complete | `cli/` | All commands: add, query, stats, trust, embeddings, etc. |
| Transport | Complete | `transport/` | Legacy HTTP + libp2p adapter |

## Building Blocks (Bricks)

Valence is composed from 13 reusable bricks. Each brick is independently tested.

| Brick | Tests | Purpose |
|-------|-------|---------|
| our-db | ~50 | Database utilities, connection management |
| our-models | ~80 | Data models, dimensional confidence |
| our-crypto | ~120 | Proxy re-encryption, ZK proofs |
| our-identity | ~60 | DID-based identity, key management |
| our-consensus | ~90 | VRF, validator selection |
| our-confidence | ~70 | Confidence scoring, aggregation |
| our-storage | ~80 | Erasure coding, Merkle trees, multi-backend |
| our-mcp-base | ~30 | Base MCP server utilities |
| our-compliance | 48 | GDPR deletion, PII scanning, tombstones |
| our-network | 662 | P2P routing, seed nodes, QoS, discovery |
| our-embeddings | 105 | Vector embeddings, OpenAI + local providers |
| our-privacy | 1,135 | Trust graph, capabilities, audit, encryption |
| our-federation | 1,397 | P2P federation, peer sync, consent, groups |

## Test Coverage

- **Valence tests:** 2,316
- **Brick tests:** ~4,063
- **Combined:** ~6,379
- **Overall coverage:** 75%
- **CI gate:** 70% project, 75% patch

## What's Not Implemented

These are aspirational features mentioned in docs but not yet built:

- **Rust transport** — rust-libp2p for higher throughput (transport/ has Python libp2p adapter)
- **Auto-ingestion** — Automatic belief extraction from conversations (manual via `insight_extract`)
- **Browser client** — Web UI for interacting with the substrate
- **Network governance transition** — Formal governance protocol beyond docs/GOVERNANCE.md
