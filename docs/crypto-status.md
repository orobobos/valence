# Cryptographic Implementation Status

Honest assessment of what's production-ready vs interface-only across ourochronos bricks.

## Production-Ready

| Brick | Component | Status | Notes |
|-------|-----------|--------|-------|
| our-db | Connection encryption | Production | Uses PostgreSQL TLS |
| our-db | Parameterized queries | Production | SQL injection prevention |
| our-identity | Key generation | Production | Ed25519 keys via cryptography lib |
| our-identity | DID creation | Production | did:key method |
| our-compliance | PII scanning | Production | Pattern-based detection |
| our-compliance | Tombstone records | Production | Deletion audit trail |

## Functional (Interface + Implementation)

| Brick | Component | Status | Notes |
|-------|-----------|--------|-------|
| our-crypto | Proxy re-encryption | Interface + mock | PRE scheme defined, mock implementation for testing |
| our-crypto | MLS messaging | Interface + mock | TreeKEM interfaces, mock key exchange |
| our-crypto | ZK proofs | Interface only | Proof generation/verification interfaces defined |
| our-privacy | Trust graph | Functional | In-memory trust propagation, works but not cryptographically verified |
| our-privacy | Capability tokens | Functional | UCAN-style tokens, signature verification present |
| our-privacy | Audit logging | Functional | Tamper-evident via hash chains |
| our-privacy | Content encryption | Interface + mock | AES-256-GCM interfaces, mock for testing |
| our-privacy | Watermarking | Interface + mock | Content fingerprinting interfaces |
| our-federation | Peer authentication | Functional | TLS + bearer token, not mutual TLS |
| our-federation | Consent chains | Functional | Stored and checked, not cryptographically signed |
| our-federation | Belief provenance | Functional | Hash chains for provenance tracking |

## Interface-Only (Needs Real Implementation)

| Brick | Component | What Exists | What's Needed |
|-------|-----------|-------------|---------------|
| our-crypto | PRE scheme | ElGamal-based interfaces | Actual elliptic curve implementation or library integration |
| our-crypto | MLS protocol | TreeKEM tree structure | Real MLS library (e.g., OpenMLS bindings) |
| our-crypto | ZK proofs | Proof/Verifier interfaces | ZK library (e.g., py-snark, bellman bindings) |
| our-consensus | BFT voting | Vote collection + tallying | Cryptographic vote verification, threshold signatures |
| our-network | End-to-end encryption | Transport encryption interfaces | Noise protocol or WireGuard integration |

## Design Decisions

1. **Why interfaces first**: The interfaces define the security contract. Mock implementations let us build and test the full system while real crypto can be plugged in incrementally.

2. **What's safe to use now**: Valence in single-user mode (no federation) relies on PostgreSQL's built-in encryption, parameterized queries, and standard auth. This is production-grade for personal use.

3. **What needs work for multi-user**: Federation, shared beliefs, and cross-node trust all need real cryptographic implementations before deploying in multi-user scenarios.

4. **Priority order**: (1) Consent chain signing, (2) peer mutual TLS, (3) belief provenance signatures, (4) capability token crypto, (5) E2E encryption, (6) ZK proofs.
