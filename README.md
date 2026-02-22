# Valence

**A knowledge system for AI agents.**

Valence ingests information from diverse sources, compiles it into useful articles through use-driven promotion, and maintains those articles as living documents — always current, always traceable to their origins, always queryable. Sources are immutable and typed. Articles are compiled on demand, not eagerly. Every article tracks which sources built it, how they contributed, and whether any of them disagree.

---

## Architecture

```
Sources (immutable, typed)
    │  ingest → store → embed (lazy)
    ▼
Article compilation (use-driven)
    │  query → surface sources → compile via inference
    ▼
Articles (versioned, right-sized)
    │  provenance links, contention flags, freshness scores
    ▼
Retrieval
    │  ranked by relevance × confidence × freshness
    ▼
Agent / CLI consumer
```

**Four layers:**

- **Sources** — raw inputs (conversations, documents, web, code, observations, tool outputs). Ingested cheaply, stored immutably. Embedding and entity extraction deferred until needed.
- **Articles** — compiled knowledge units. Created when a query surfaces ungrouped sources; updated when new source material arrives. Each article is right-sized for context windows and carries full provenance.
- **Provenance** — typed relationships from sources to articles: `originates`, `confirms`, `supersedes`, `contradicts`, `contends`. Contention is surfaced at retrieval time, not silently resolved.
- **Traces** — usage signals that drive self-organization. Articles used frequently stay well-maintained; unused articles deprioritize in retrieval and are candidates for organic forgetting.

**Inference router** handles five task types (compile, update, classify, contention detection, split) via a single configured backend. Falls back to degraded mode with explicit visibility — outputs produced in degraded mode are flagged and requeued when inference becomes available.

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/ourochronos/valence.git
cd valence
docker compose up -d
```

PostgreSQL + pgvector starts on `localhost:5433`. The Valence API server starts on `http://localhost:8420`. Schema is applied automatically.

### Database only (for development)

```bash
docker compose up -d postgres
```

Then run the server locally:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
valence init          # apply schema migrations
```

Set connection info via environment or `.env`:

```bash
VKB_DB_HOST=localhost
VKB_DB_PORT=5433
VKB_DB_NAME=valence
VKB_DB_USER=valence
VKB_DB_PASSWORD=valence
```

### Configure inference

By default, the system runs in degraded mode (concatenation fallback). Configure a real backend:

```bash
# Gemini 2.5 Flash via local gemini CLI (no API key needed)
valence config inference gemini

# Cerebras (ultra-low-latency classification)
valence config inference cerebras --api-key YOUR_KEY

# Local Ollama (fully offline)
valence config inference ollama --model qwen3:30b

# View current config
valence config inference show
```

### Smoke test

```bash
# Ingest a source
valence sources ingest "Python's GIL was replaced in 3.13 by per-interpreter locks." \
  --type document --title "Python 3.13 release notes"

# Search sources
valence sources search "Python GIL"

# Search articles (compiled on first use)
valence articles search "Python concurrency"

# Get an article with its provenance
valence articles get <article-id> --provenance
```

---

## CLI Usage

### Sources

```bash
# Ingest from stdin or argument
valence sources ingest "Content here" --type web --title "My Source" --url https://example.com
valence sources ingest "$(cat notes.txt)" --type document

# List sources (filterable by type)
valence sources list
valence sources list --type conversation --limit 50

# Get a specific source
valence sources get <source-id>

# Search sources (full-text)
valence sources search "search terms"
```

**Source types:** `document`, `conversation`, `web`, `code`, `observation`, `tool_output`, `user_input`

### Articles

```bash
# Search compiled articles (triggers compilation if needed)
valence articles search "query about anything"
valence articles search "Python" --domain engineering

# Get article with full provenance
valence articles get <article-id> --provenance

# List recent articles
valence articles list

# Create an article manually (operator-authored)
valence articles create "This is article content." --title "My Article"
valence articles create "Agent-synthesized insight" --author-type agent
```

### Provenance

```bash
# List all sources for an article
valence provenance get <article-id>

# Trace a specific claim back to contributing sources
valence provenance trace <article-id> "the claim text to trace"

# Link a source to an article with a typed relationship
valence provenance link <article-id> <source-id> --relationship confirms
valence provenance link <article-id> <source-id> --relationship contradicts --notes "Newer data disagrees"
```

**Relationship types:** `originates`, `confirms`, `supersedes`, `contradicts`, `contends`

### Configuration

```bash
# Inference backend
valence config inference show
valence config inference gemini --model gemini-2.5-flash
valence config inference cerebras --api-key KEY --model llama-4-scout-17b-16e-instruct
valence config inference ollama --host http://localhost:11434 --model qwen3:30b
```

### Global flags

```bash
valence --json articles search "query"          # JSON output
valence --output table sources list             # table output
valence --server http://remote:8420 stats       # remote server
valence --timeout 60 articles search "big query"
```

---

## Configuration

Configuration lives in two places:

**Environment / `.env`** — database connection and server binding:

```bash
VKB_DB_HOST=localhost
VKB_DB_PORT=5433
VKB_DB_NAME=valence
VKB_DB_USER=valence
VKB_DB_PASSWORD=valence
VALENCE_HOST=127.0.0.1
VALENCE_PORT=8420
```

**`system_config` table** — inference backend (written by `valence config inference`):

```json
{
  "provider": "gemini",
  "model": "gemini-2.5-flash"
}
```

The server reads `system_config` at startup. Changes take effect on restart.

---

## Integration

### OpenClaw

Valence integrates with OpenClaw via CLI wrapping. OpenClaw calls `valence` subcommands directly; no MCP server required.

```bash
# OpenClaw skill wraps the CLI:
valence sources ingest "$CONTENT" --type observation
valence articles search "$QUERY"
```

Inference backend is configurable per platform — call `valence config inference` to set the backend appropriate for your environment.

### Claude Code

Claude Code integration via plugin system is planned (future). The plugin will call `valence` CLI commands and inherit whatever inference backend is configured. No CLAUDE.md requirement on users.

---

## Development

```bash
git clone https://github.com/ourochronos/valence.git
cd valence
git checkout v2/knowledge-system

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Start the database
docker compose up -d postgres

# Apply schema
valence init

# Run tests
pytest tests/ -x -q

# Lint
ruff check src/
```

**Current branch:** `v2/knowledge-system` — v2 rewrite. `main` contains v1 (beliefs, federation, MCP, 78 tables). v2 replaces all of that with 20 tables, CLI-first, provenance-native.

---

## Data Sovereignty

All inference runs in the US. Gemini Flash via local CLI, Cerebras (US cloud), or Ollama (local). No direct calls to non-US endpoints. All data stays local unless you explicitly federate (not in v2 scope).

---

## License

MIT
