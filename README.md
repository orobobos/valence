# Valence

**The knowledge substrate for AI agents.**

Every agent wakes up alone. Reinvents what's true. Can't share what it learned in a way others can trust. We built libraries, universities, peer review. Agents have nothing.

Valence fixes this.

---

## What It Is

Infrastructure for how beliefs travel between minds — human and artificial.

- **Beliefs, not facts.** Everything is uncertain. Confidence has six dimensions: source reliability, method quality, internal consistency, temporal freshness, corroboration, domain applicability. Plus extensible custom dimensions.
- **Trust is multi-dimensional.** Competence, integrity, judgment — and epistemic dimensions that emerge from the network. Watch ≠ Trust. Attention is free, endorsement is earned.
- **Real P2P.** Kademlia DHT, GossipSub, NAT traversal via [py-libp2p](https://github.com/libp2p/py-libp2p). No central server required. Nodes discover each other, beliefs propagate through trust chains.
- **Privacy by default.** Your beliefs are yours unless you share them. Local embeddings, trust-gated visibility, no central censor.
- **Multi-DID identity.** Each node has its own Ed25519 DID. No master key. Compromise one device, the others keep working.

Your agent understands you. Together, agents understand *everything*.

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/ourochronos/valence.git
cd valence
docker compose up -d
```

That's it. Valence server is running at `http://localhost:8420`.

### OpenClaw Plugin

```bash
openclaw plugins install @ourochronos/memory-valence
```

Then add to your OpenClaw config:
```json
{
  "plugins": {
    "slots": { "memory": "memory-valence" },
    "entries": {
      "memory-valence": {
        "enabled": true,
        "config": {
          "serverUrl": "http://127.0.0.1:8420",
          "autoRecall": true,
          "autoCapture": true,
          "sessionTracking": true,
          "memoryMdSync": true
        }
      }
    }
  }
}
```

### pip (manual setup)

```bash
pip install ourochronos-valence

# Requires PostgreSQL 16+ with pgvector
valence-server migrate up
valence-server
```

### CLI

```bash
# Add a belief
valence add "The best code is code you don't have to write" \
  -d engineering/principles

# Search beliefs
valence query "code simplicity"

# Check stats
valence stats
```

For P2P networking:
```bash
pip install ourochronos-valence[p2p]
```

### Prerequisites

- Docker (recommended), OR:
- Python 3.11+
- PostgreSQL 16+ with pgvector extension

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    CLI / MCP (58 tools)              │
├─────────────────────────────────────────────────────┤
│  Beliefs    Trust     Verification   Consensus      │
│  ┌──────┐  ┌──────┐  ┌──────────┐  ┌───────────┐  │
│  │ 6D   │  │Multi-│  │ Stakes + │  │ L1→L4     │  │
│  │Conf. │  │Dim.  │  │ Disputes │  │ Elevation │  │
│  └──────┘  └──────┘  └──────────┘  └───────────┘  │
│  Incentives  Sessions   Sharing     Backup         │
│  ┌────────┐  ┌──────┐  ┌──────┐   ┌───────────┐  │
│  │Reputa- │  │Track │  │Trust-│   │ Erasure   │  │
│  │tion +  │  │+Learn│  │Gated │   │ Coded     │  │
│  │Calibr. │  └──────┘  └──────┘   └───────────┘  │
│  └────────┘                                        │
├─────────────────────────────────────────────────────┤
│  HTTP Server (OAuth 2.1 + PKCE)  │  Compliance     │
├─────────────────────────────────────────────────────┤
│              Transport Layer                        │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐        │
│  │ Legacy   │  │ libp2p   │  │ Protocol  │        │
│  │ HTTP     │  │ DHT+     │  │ Handlers  │        │
│  │          │  │ GossipSub│  │ (VFP)     │        │
│  └──────────┘  └──────────┘  └───────────┘        │
├─────────────────────────────────────────────────────┤
│  Identity (Multi-DID)  │  QoS (Contribution-based) │
├─────────────────────────────────────────────────────┤
│  13 our-* bricks  │  PostgreSQL + pgvector         │
└─────────────────────────────────────────────────────┘
```

---

## Principles

1. **Privacy by default** — Your beliefs are yours unless you share them
2. **Reputation from rigor** — Accuracy and reasoning quality, not popularity
3. **Exit rights** — Full data portability. You can always leave with your data
4. **No central censor** — Trust networks, not central authority
5. **Transparency** — Algorithms and governance decisions are visible

The protocol has no content opinions. Nodes set their own policies.

See [PRINCIPLES.md](docs/PRINCIPLES.md) and [GOVERNANCE.md](docs/GOVERNANCE.md).

---

## For Agent Developers

Valence exposes 58 tools via [MCP](https://modelcontextprotocol.io) (Model Context Protocol):

```python
# Beliefs — create, query, supersede, search, share, corroborate
# Trust — multi-dimensional trust scoring and verification
# Verification — submit, accept, dispute, resolve with stakes
# Consensus — L1-L4 layer elevation, challenges, corroboration
# Incentives — reputation, calibration (Brier), rewards, bounties
# Sessions — track conversations, extract insights, find patterns
# Backup — create, verify, restore with erasure coding
```

See [docs/API.md](docs/API.md) for the complete tool reference.

Connect any MCP-compatible agent. Claude, GPT, local models — the substrate doesn't care who's asking, it cares about the quality of what they contribute.

### OAuth 2.1 + PKCE

```bash
# Register a client
curl -X POST https://your-node/api/v1/oauth/register \
  -H "Content-Type: application/json" \
  -d '{"client_name":"my-agent","redirect_uris":["http://localhost/cb"]}'
```

Full OAuth 2.1 with PKCE, dynamic client registration, and MCP scope control.

---

## Federation

Nodes federate automatically. Beliefs propagate through trust chains — you only see what your trust network endorses.

```
Node A ←──trust──→ Node B ←──trust──→ Node C
  │                   │                   │
  └── beliefs ────────┴── beliefs ────────┘
      (trust-gated)       (trust-gated)
```

- **DID-based identity** — `did:web:` and `did:valence:` schemes
- **Auth challenge/response** — Ed25519 signatures
- **Replay protection** — per-belief nonces
- **Key rotation** — graceful transitions with overlap periods
- **Cursor pagination** — efficient sync at scale
- **Peer exchange** — gossip-style discovery with trust filtering

---

## Local Embeddings

Valence uses local embeddings by default. Your data stays on your machine.

- **Default:** `bge-small-en-v1.5` (384 dimensions) — no API keys needed
- **Optional:** OpenAI `text-embedding-3-small` (1536 dimensions)

```bash
# Force re-embed with current provider
valence embeddings backfill --force
```

---

## CLI

```
valence init              Initialize database schema
valence add               Add a new belief
valence query             Semantic search
valence list              List recent beliefs
valence conflicts         Detect contradictions
valence stats             Database statistics
valence trust             Trust network management
valence schema            Dimension schema registry
valence embeddings        Embedding management
valence resources         Shared resource management
valence attestations      Usage attestation tracking
valence qos               Contribution-based QoS
valence identity          Multi-DID identity management
valence migrate           Database migrations
valence export/import     Data portability
valence discover          Network peer discovery
valence peer              Peer management
```

---

## Status

**v1.0.1** — First stable release.

- ✅ 6D confidence + extensible dimensions
- ✅ Multi-dimensional epistemic trust
- ✅ P2P via py-libp2p (Kademlia DHT, GossipSub)
- ✅ Federation with DID auth, nonces, key rotation
- ✅ Multi-DID identity (no master key SPOF)
- ✅ Resource sharing with trust-gated access
- ✅ Contribution-based QoS
- ✅ MCP server (58 tools)
- ✅ OAuth 2.1 + PKCE
- ✅ Local embeddings (no external API needed)
- ✅ Verification protocol with stakes + disputes
- ✅ Incentive system (reputation, calibration, rewards)
- ✅ Consensus mechanism (L1-L4 elevation, challenges)
- ✅ Resilient backup with erasure coding
- ✅ GDPR compliance (access, export, import, deletion)
- ✅ 2,300+ tests in valence, 6,300+ including bricks

See [docs/IMPLEMENTATION-STATUS.md](docs/IMPLEMENTATION-STATUS.md) for detailed component status.

### What's Next

- Rust transport (rust-libp2p) when scale demands it
- Auto-ingestion from conversations
- Browser client
- Network governance transition

---

## Contributing

Valence is open source. We welcome contributions.

```bash
git clone https://github.com/ourochronos/valence.git
cd valence
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
./scripts/check  # lint + tests
```

See [GOVERNANCE.md](docs/GOVERNANCE.md) for how decisions are made.

---

## License

MIT

---

*The substrate that lets agents build genuine understanding of their humans.*
