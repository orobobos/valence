# Valence Federation

> Share knowledge across sovereign nodes while preserving privacy and control.

---

## What Is Federation?

Federation enables multiple Valence nodes to share beliefs and knowledge while maintaining sovereignty over their data. Each node remains independent—no central authority controls the network.

```
┌─────────────────┐         ┌─────────────────┐
│   Your Node     │◄───────►│   Peer Node     │
│  (sovereign)    │  trust  │  (sovereign)    │
│                 │  link   │                 │
│  - Your beliefs │         │  - Their beliefs│
│  - Your control │         │  - Their control│
│  - Your privacy │         │  - Their privacy│
└─────────────────┘         └─────────────────┘
        │                           │
        │                           │
        ▼                           ▼
   Only share what            Only share what
   YOU choose to share        THEY choose to share
```

**Key principle:** Your data never leaves your node without your explicit consent.

---

## Privacy Model

Federation is built on a **consent-based, privacy-first** architecture:

### What's Private By Default

| Data | Default | Requires Consent |
|------|---------|------------------|
| Local beliefs | 🔒 Private | Yes |
| Personal notes | 🔒 Private | Never shared |
| Query history | 🔒 Private | N/A |
| Trust decisions | 🔒 Private | N/A |

### What Can Be Shared (With Consent)

| Data | Share Level | Privacy |
|------|-------------|---------|
| Belief content | `belief_only` | High - no metadata |
| Belief + source | `with_provenance` | Medium - includes derivation |
| Full attribution | `full` | Low - includes holder info |

### Visibility Levels

Each belief has a visibility that controls federation behavior:

```python
visibility:
  private     # Never leaves your node
  trusted     # Only to explicitly trusted peers
  federated   # Shared across federation network
  public      # Discoverable by anyone
```

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          FEDERATION NETWORK                             │
│                                                                        │
│  ┌────────────────┐      ┌────────────────┐      ┌────────────────┐   │
│  │ Node A         │      │ Node B         │      │ Node C         │   │
│  │ valence.       │      │ valence2.      │      │ other.         │   │
│  │ zonk1024.net   │◄────►│ zonk1024.net   │◄────►│ example.com    │   │
│  │                │      │                │      │                │   │
│  │ ┌────────────┐ │      │ ┌────────────┐ │      │ ┌────────────┐ │   │
│  │ │ PostgreSQL │ │      │ │ PostgreSQL │ │      │ │ PostgreSQL │ │   │
│  │ │ + pgvector │ │      │ │ + pgvector │ │      │ │ + pgvector │ │   │
│  │ └────────────┘ │      │ └────────────┘ │      │ └────────────┘ │   │
│  │                │      │                │      │                │   │
│  │ ┌────────────┐ │      │ ┌────────────┐ │      │ ┌────────────┐ │   │
│  │ │ Federation │ │      │ │ Federation │ │      │ │ Federation │ │   │
│  │ │   Server   │ │      │ │   Server   │ │      │ │   Server   │ │   │
│  │ └────────────┘ │      │ └────────────┘ │      │ └────────────┘ │   │
│  └────────────────┘      └────────────────┘      └────────────────┘   │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘

Protocol: HTTP/2 + TLS 1.3
Identity: DIDs (did:vkb:web:<domain>)
Auth: Ed25519 challenge-response
```

---

## Trust Model

Trust is **earned, not assumed**. The system uses cryptographic verification and behavioral scoring:

### Trust Levels

| Level | Score | Meaning |
|-------|-------|---------|
| Unknown | 0.0 | Never interacted |
| Acquaintance | 0.3 | Some interaction, basic verification |
| Trusted | 0.6 | Consistent good behavior |
| Highly Trusted | 0.8+ | Long history, high-quality contributions |

### How Trust Is Earned

1. **Introduction handshake** — Nodes exchange DIDs and verify signatures
2. **Belief exchange** — Quality beliefs increase trust, bad ones decrease it
3. **Consistency** — Nodes that stay online and respond reliably gain trust
4. **Endorsements** — Other trusted nodes can vouch for a peer

### Trust Affects Confidence

When you receive a belief from a peer, its effective confidence is weighted:

```
effective_confidence = belief_confidence × peer_trust_level
```

A 90% confidence belief from a 50% trusted peer → 45% effective confidence.

---

## Core Operations

### 1. Discover Peers

```bash
# Well-known endpoint for node metadata
curl https://valence.example.com/.well-known/vfp-node-metadata
```

Returns the node's DID document with capabilities and service endpoints.

### 2. Share Beliefs

```bash
# Export beliefs for a peer
valence export --to did:vkb:web:peer.example.com -d tech --min-confidence 0.7

# Share directly via federation protocol
# (handled by federation server)
```

### 3. Query Across Federation

```bash
# Query including peer beliefs
valence query "PostgreSQL optimization" --scope federated

# Results include both local and federated beliefs with source attribution
```

### 4. Import Beliefs

```bash
# Import from a peer
valence import beliefs.json --from did:vkb:web:peer.example.com
```

---

## Getting Started

1. **Deploy a node** → See [DEPLOYMENT.md](./DEPLOYMENT.md)
2. **Configure federation** → Enable federation in your node config
3. **Add peers** → Exchange DIDs with trusted parties
4. **Share beliefs** → Mark beliefs as `federated` visibility
5. **Query the network** → Use `--scope federated` for cross-node queries

---

## Design Principles

1. **User Sovereignty** — You control your data completely
2. **Structural Integrity** — Trust enforced by cryptography, not promises
3. **Privacy by Default** — Nothing shared without explicit consent
4. **Aggregation Serves Users** — Federation exists to help you, not extract from you
5. **Openness** — Protocol is open, nodes can fork, no vendor lock-in

---

## Security Guarantees

| Guarantee | Mechanism |
|-----------|-----------|
| **Identity verification** | Ed25519 signatures on all messages |
| **Content integrity** | Beliefs are signed by origin node |
| **Transport security** | TLS 1.3 required |
| **Forward secrecy** | Key rotation on trust changes |
| **Replay protection** | Nonces in authentication challenges |

---

## What Federation Is NOT

- ❌ **Not a blockchain** — No global consensus, no mining, no tokens
- ❌ **Not a social network** — No followers, likes, or viral content
- ❌ **Not centralized** — No company controls the network
- ❌ **Not required** — A standalone node works perfectly fine
- ❌ **Not automatic** — You must explicitly choose to federate

---

## Related Documentation

- [DEPLOYMENT.md](./DEPLOYMENT.md) — How to deploy a federated node
- [OPERATIONS.md](./OPERATIONS.md) — Day-to-day operations and troubleshooting
- [AGGREGATION.md](./AGGREGATION.md) — Privacy-preserving belief aggregation
- [../FEDERATION_PROTOCOL.md](../FEDERATION_PROTOCOL.md) — Protocol specification
- [../TRUST_MODEL.md](../TRUST_MODEL.md) — Trust graph details

---

*"Sovereignty through architecture, not policy."*
