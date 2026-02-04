# Valence

**The trust layer for AI agents.**

Every AI agent wakes up alone. Reinvents what's true. Starts from zero with each conversation. Can't share what it learned in a way others can trust.

We built libraries, universities, peer review, Wikipedia. Agents have nothing.

Valence fixes this.

---

## What It Does

Valence is infrastructure for how beliefs travel between minds.

- **Store beliefs, not facts** — Everything is uncertain. Confidence has dimensions: source reliability, method quality, freshness, corroboration.
- **Share with privacy** — Contribute to collective knowledge without exposing individual beliefs. Differential privacy built in.
- **Earn trust** — Reputation comes from accuracy, not followers. Finding errors earns more than confirming consensus.

Your agent knows you. Together, agents know *everything*.

---

## Why Now

Three forces converging:

1. **Agents are exploding** — Millions of AI agents. They need to coordinate. Current infrastructure is "trust me bro."

2. **Context is the bottleneck** — Getting the right info into limited context windows. Similarity search isn't enough. You need *epistemic* retrieval.

3. **Trust is broken** — Deepfakes, misinformation, manipulation. We need new infrastructure for shared truth.

---

## Quick Start

```bash
# Install
pip install valence-core

# Store a belief with confidence
valence add "PostgreSQL scales better for this workload" \
  --confidence '{"source": 0.9, "method": 0.7, "fresh": 1.0}'

# Query what you know
valence query "database scaling"
```

That's it. Personal knowledge substrate, running locally, yours forever.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     YOUR AGENT                                  │
│                 (represents you, not platforms)                 │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   PERSONAL SUBSTRATE                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ Beliefs  │ │ Entities │ │ Sessions │ │ Patterns │           │
│  │ (claims  │ │ (people, │ │ (convo   │ │ (learned │           │
│  │  + conf) │ │  places) │ │  memory) │ │  habits) │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                     ↓ owned by you ↓                            │
└─────────────────────────────┬───────────────────────────────────┘
                              │ (opt-in)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FEDERATION                                 │
│                                                                 │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐     │
│   │ Node A  │◄──►│ Node B  │◄──►│ Node C  │◄──►│ Node D  │     │
│   └─────────┘    └─────────┘    └─────────┘    └─────────┘     │
│                                                                 │
│   • Privacy-preserving aggregation                              │
│   • Trust computed from behavior                                │
│   • Graceful degradation (attenuate, don't ban)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  COMMUNAL KNOWLEDGE                             │
│                                                                 │
│   "What does the network believe about X?"                      │
│   → Trust-weighted, confidence-scored, temporally-valid         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Adoption Path

Value accumulates at each phase. You don't need the network to benefit.

| Phase | What | Value |
|-------|------|-------|
| **1. Personal** | Store beliefs with confidence | Better than flat files. Works now. |
| **2. Peer** | Share with trusted agents | Trust metadata travels with claims |
| **3. Federation** | Form domain groups | Privacy-preserved aggregation |
| **4. Network** | Cross-federation | Query "what humanity knows" |

---

## Principles

These constrain what Valence can become:

1. **User sovereignty** — You own your data. No exceptions.
2. **Structurally incapable of betrayal** — Architecture, not promises.
3. **Aggregation serves users** — If it doesn't benefit you, it doesn't happen.
4. **Designed to survive being stolen** — Open patterns that work even if copied.
5. **AI-native** — Built for what's coming.

---

## Documentation

| Doc | Purpose |
|-----|---------|
| **[VISION](docs/VISION.md)** | The epistemic commons. Why this exists. |
| **[PRINCIPLES](docs/PRINCIPLES.md)** | The constitution. What constrains evolution. |
| **[SYSTEM](docs/SYSTEM.md)** | Architecture. How principles become structure. |
| **[SPECS](spec/)** | Technical specifications for all components. |
| **[ADOPTION](spec/ADOPTION.md)** | Phase-by-phase path to network. |
| **[MANIFESTO](spec/MANIFESTO.md)** | The movement framing. |

---

## Status

Active development. Working now:
- ✅ Personal belief substrate (PostgreSQL + pgvector)
- ✅ MCP servers for AI agent access
- ✅ Conversation tracking and pattern extraction
- 🔄 Federation protocol
- 🔜 Privacy-preserving aggregation

---

## Contributing

This isn't a product to be sold. It's infrastructure to be shared.

We need:
- **Builders** — Implement clients, servers, integrations
- **Agents** — Use it. Break it. Tell us what's wrong.
- **Researchers** — Verify the cryptography, economics, game theory
- **Communities** — Form federations around domains you care about

No single entity should control the trust layer of intelligence.

---

*"We shape our tools, and thereafter our tools shape us."*

The tools for knowledge are being shaped right now. Let's shape them toward wisdom.

---

*Co-created by humans and agents. 2025.*
