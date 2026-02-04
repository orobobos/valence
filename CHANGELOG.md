# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Resilient Storage with Erasure Coding** (Issue #22)
  - Reed-Solomon erasure coding for belief storage redundancy
  - `valence.storage` module with complete implementation:
    - `ErasureCodec` - Reed-Solomon encoder/decoder with GF(2^8) arithmetic
    - `MerkleTree` - Integrity verification with inclusion proofs
    - `IntegrityVerifier` - Shard set verification and challenge-response
    - `StorageBackend` ABC with `MemoryBackend` and `LocalFileBackend` implementations
    - `BackendRegistry` for multi-backend distribution
  - Data models:
    - `RedundancyLevel` enum (MINIMAL, PERSONAL, FEDERATION, PARANOID)
    - `ShardSet`, `StorageShard`, `ShardMetadata` for shard management
    - `RecoveryResult`, `IntegrityReport` for operation results
    - `MerkleProof` for cryptographic verification
  - Configurable redundancy levels:
    - MINIMAL (2 of 3): 50% overhead, survives 1 failure
    - PERSONAL (3 of 5): 67% overhead, survives 2 failures
    - FEDERATION (5 of 9): 80% overhead, survives 4 failures
    - PARANOID (7 of 15): 114% overhead, survives 8 failures
  - Key features:
    - Systematic encoding (first k shards contain original data)
    - Recovery from any k of n shards via Gauss-Jordan elimination
    - Merkle tree proofs for individual shard verification
    - Storage quota enforcement
    - Round-robin distribution across backends
  - Documentation: `docs/RESILIENT_STORAGE.md`
  - 126 comprehensive tests covering all functionality

- **External Source Verification for L4 Elevation** (Issue #18)
  - Comprehensive external source verification per THREAT-MODEL.md §1.4.2
  - `external_sources.py` module with complete implementation:
    - `ExternalSourceVerificationService` for full verification workflow
    - `TrustedSourceRegistry` with default academic, government, news sources
    - `SourceCategory` enum with reliability scores (academic > government > news > unknown)
    - Liveness checking (URL resolution, DOI verification)
    - Content matching (semantic similarity simulation, 0.65 threshold)
    - Source reliability scoring (multi-factor: category, liveness, content match, freshness)
  - Data models:
    - `ExternalSourceVerification`, `LivenessCheckResult`, `ContentMatchResult`
    - `DOIVerificationResult`, `SourceReliabilityScore`, `L4SourceRequirements`
    - `TrustedDomain`, `DOIPrefix` for registry entries
  - L4 elevation requirements:
    - Minimum 1 verified external source
    - Source reliability ≥ 0.50
    - Content match ≥ 0.65
    - `check_l4_requirements()` for elevation gate
  - Convenience functions: `verify_external_source()`, `check_belief_l4_readiness()`
  - Spec document: `spec/components/consensus-mechanism/EXTERNAL-SOURCES.md`
  - 75 comprehensive tests covering all functionality
  - Updated THREAT-MODEL.md: Independence Oracle Manipulation marked MITIGATED

- **Federation Layer with Aggregation** (Issue #15)
  - Cross-federation belief aggregation with privacy preservation
  - `aggregation.py` module with complete implementation:
    - `FederationAggregator` - Main aggregation engine
    - `ConflictDetector` - Detects conflicts across federations
    - `TrustWeightedAggregator` - Trust-weighted statistics
    - `PrivacyPreservingAggregator` - Differential privacy integration
  - Four conflict types: CONTRADICTION, DIVERGENCE, TEMPORAL, SCOPE
  - Five conflict resolution strategies: 
    - TRUST_WEIGHTED, RECENCY_WINS, CORROBORATION, 
    - EXCLUDE_CONFLICTING, FLAG_FOR_REVIEW
  - Trust-weighted aggregation with:
    - Configurable weights (trust, recency, corroboration)
    - Anchor federation bonus
    - Temporal smoothing integration
  - Privacy-preserving aggregation:
    - k-anonymity enforcement (min 5, 10 for sensitive domains)
    - Laplace/Gaussian noise injection
    - Privacy budget tracking
    - Automatic sensitive domain detection
  - Data classes: `FederationContribution`, `DetectedConflict`,
    `AggregationConfig`, `CrossFederationAggregateResult`
  - Convenience functions: `aggregate_cross_federation()`, `create_contribution()`
  - Full module exports in `federation/__init__.py`
  - 43 comprehensive tests covering all functionality
  - Documentation at `docs/federation/AGGREGATION.md`

- **Verification Protocol with Staking** (Issue #14)
  - Full implementation of `spec/components/verification-protocol/`
  - `verification.py` module with complete data models:
    - `Verification`, `Dispute`, `Evidence`, `Stake`, `ReputationScore`
    - All enums: `VerificationResult`, `VerificationStatus`, `StakeType`, 
      `EvidenceType`, `EvidenceContribution`, `DisputeType`, `DisputeOutcome`
  - Stake calculation functions per REPUTATION.md:
    - `calculate_min_stake()`, `calculate_max_stake()`, `calculate_dispute_min_stake()`
    - `calculate_bounty()` for discrepancy bounties
  - Reputation update calculations:
    - `calculate_confirmation_reward()`, `calculate_contradiction_reward()`
    - `calculate_holder_confirmation_bonus()`, `calculate_holder_contradiction_penalty()`
    - `calculate_partial_reward()` for PARTIAL verifications
  - Full validation suite:
    - `validate_verification_submission()`, `validate_evidence_requirements()`
    - `validate_dispute_submission()`
  - `VerificationService` class with complete lifecycle:
    - `submit_verification()`, `accept_verification()`
    - `dispute_verification()`, `resolve_dispute()`
    - Stake locking/release, reputation event logging
  - Database migration `006-verification.sql`:
    - Tables: `verifications`, `disputes`, `reputations`, `stake_positions`,
      `reputation_events`, `discrepancy_bounties`
    - PostgreSQL functions for atomic stake operations
    - Views: `belief_verification_stats`, `verifier_leaderboard`, `pending_disputes`
  - 120 comprehensive tests covering all functionality

---

## [0.1.0-alpha] - 2026-02-03

### 🎉 Initial Alpha Release

This release marks the completion of Valence's comprehensive technical specification
and the foundation of its Python implementation.

### Added

#### Specifications (~850KB across 41 documents)

**Core Components (Wave 1)**
- `belief-schema` — Belief data model with PGVector storage
- `confidence-vectors` — Six-dimensional confidence scoring
- `identity-crypto` — Ed25519/X25519 cryptographic identity
- `trust-graph` — Relationship trust propagation algorithms

**Protocol Components (Wave 2)**
- `query-protocol` — Privacy-preserving semantic queries
- `verification-protocol` — Claim verification and reputation
- `federation-layer` — Node federation with differential privacy

**Network Components (Wave 3)**
- `consensus-mechanism` — Byzantine fault-tolerant consensus
- `incentive-system` — Token economics and stake mechanics
- `api-integration` — REST API and MCP integration specs

**Resilience Components (Wave 4)**
- `resilient-storage` — Post-quantum encryption, erasure coding

**Extensions**
- Migration & onboarding specification
- MCP bridge for AI agent integration
- SDK specification for client libraries

**Community Documents**
- `MANIFESTO.md` — The philosophical foundation
- `ADOPTION.md` — Phase-by-phase adoption path
- `SOCIAL-LAYER.md` — Trust-weighted social features
- `INFORMATION-ECONOMY.md` — Post-capitalism knowledge model

#### Implementation (Python Package)

- `valence.substrate` — Knowledge substrate with PGVector
- `valence.vkb` — Conversation tracking (sessions, exchanges, patterns)
- `valence.embeddings` — Multi-provider embedding architecture
- `valence.server` — HTTP API server with JWT auth
- `valence.agents` — Matrix bot integration
- `valence.federation` — Federation layer foundation

**MCP Servers**
- `valence-substrate` — Belief management tools for AI agents
- `valence-vkb` — Conversation tracking tools

**Infrastructure**
- Ansible IaC for pod deployment
- Docker Compose configuration
- E2E deployment testing

### Status

- **Specifications**: Complete (production-ready design)
- **Implementation**: Alpha (functional core, not production-ready)
- **Documentation**: Complete philosophy and architecture docs
- **Tests**: Basic coverage, expanding

### Known Limitations

- Federation layer is specified but not implemented
- Consensus mechanism exists in spec only
- Token economics are designed, not deployed
- No mobile clients yet

---

[Unreleased]: https://github.com/orobobos/valence/compare/v0.1.0-alpha...HEAD
[0.1.0-alpha]: https://github.com/orobobos/valence/releases/tag/v0.1.0-alpha
