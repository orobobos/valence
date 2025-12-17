# Valence

A universal, AI-driven platform where users interact with services through personal agents while maintaining data ownership through federated, privacy-preserving aggregation.

## The Vision

Your agent knows you. It represents you—not platforms, not advertisers, not anyone else. Your data stays yours. When millions of agents aggregate their humans' values (with consent, with privacy preserved), that collective voice has power. Power to influence markets, policy, institutions.

This is Valence: the capacity to connect, to affect, to bond.

## Founding Documents

- **[PRINCIPLES.md](docs/PRINCIPLES.md)** — The constitution. These constrain what Valence can become.
- **[SYSTEM.md](docs/SYSTEM.md)** — The architecture. How principles become structure.
- **[UNKNOWNS.md](docs/UNKNOWNS.md)** — Honest gaps. What we don't know yet.

## Knowledge Base Architecture

Valence uses modular knowledge bases with clear separation:

- **Schema** (in repo) — Structure definitions, migrations, constraints
- **Data** (external) — Instance-specific, moving to cloud service

### KB Scopes

| Scope | Purpose | Location |
|-------|---------|----------|
| Personal | User values, preferences, agent memory | Cloud (planned) |
| Project | Decisions, state, progress for this project | Local/Cloud |
| Agent | Operational patterns, consistency across sessions | With Personal |

### Schema Modules

- `schema.sql` — Core entries, tags, relationships, modules
- `schema_conversations.sql` — Session tracking at micro/meso/macro scales
- `schema_embeddings.sql` — Multi-provider embedding registry

## Getting Started

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install package
pip install -e .

# Initialize schemas (creates local KB)
python -c "from valence.kb import init_schemas; init_schemas()"
```

## Development

This project is developed using its own principles:

1. **Human intent** → Define what needs to exist
2. **Collaborative design** → Derive decisions from principles
3. **AI implementation** → Claude implements, principles constrain
4. **Knowledge capture** → Decisions accumulate in KB
5. **Reflection** → Did the process follow principles?

## MCP Server

Valence exposes tools via Model Context Protocol for AI agent access:

```bash
# Run the MCP server
./valence-mcp
```

Tools include session management, exchange capture, insight extraction, and pattern tracking.

## Status

Active development. Current focus:
- Conversation tracking and curation
- Multi-provider embedding architecture
- Cloud migration path for personal KB

### Pending Architecture Work

- Library restructuring (valence-core, valence-mcp)
- Schema migration strategy
- Configuration management
- MCP tool interface versioning

---

*Co-created by Chris and Claude. December 2025.*
