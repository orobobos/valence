# Valence

A universal, AI-driven platform where users interact with services through personal agents while maintaining data ownership through federated, privacy-preserving aggregation.

## The Vision

Your agent knows you. It represents you—not platforms, not advertisers, not anyone else. Your data stays yours. When millions of agents aggregate their humans' values (with consent, with privacy preserved), that collective voice has power. Power to influence markets, policy, institutions.

This is Valence: the capacity to connect, to affect, to bond.

## Founding Documents

- **[PRINCIPLES.md](docs/PRINCIPLES.md)** — The constitution. These constrain what Valence can become.
- **[SYSTEM.md](docs/SYSTEM.md)** — The architecture. How principles become structure.
- **[UNKNOWNS.md](docs/UNKNOWNS.md)** — Honest gaps. What we don't know yet.

## The Knowledge Base

Valence uses a knowledge base (`valence.kb.sqlite`) as first-class project state. The KB tracks:

- Beliefs, decisions, principles, unknowns
- Provenance (where things came from)
- Relationships between entries
- Artifacts (external files and their state)

The KB is the project's memory. It commits with the code.

## Getting Started

```bash
# Initialize the KB with founding documents
python scripts/seed.py
```

## Development

This project is developed using its own principles:

1. **Human intent** → Define what needs to exist
2. **Collaborative design** → Derive decisions from principles
3. **AI implementation** → Claude implements, principles constrain
4. **Knowledge capture** → Decisions accumulate in KB
5. **Reflection** → Did the process follow principles?

## Status

This is the seed. Dawn, not sunset.

---

*Co-created by Chris and Claude. December 2024.*
