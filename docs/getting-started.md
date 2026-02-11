# Getting Started with Valence

Valence is a personal knowledge substrate that gives Claude persistent memory across sessions. It stores beliefs, tracks conversations, learns patterns, and grows smarter over time.

## Prerequisites

- Python 3.11+
- PostgreSQL 16 with pgvector extension
- Claude Code CLI
- (Optional) OpenAI API key for semantic search embeddings

## Quick Start (Docker)

The fastest way to get running:

```bash
# Clone the repo
git clone https://github.com/ourochronos/valence.git
cd valence

# Copy environment template
cp .env.example .env
# Edit .env if you want to customize (defaults work fine)

# Start PostgreSQL with pgvector
docker compose up -d

# Wait for healthy database
docker compose ps  # Should show "healthy"

# Install valence
pip install -e .

# Verify
valence-mcp --health-check
```

## Quick Start (Manual PostgreSQL)

If you already have PostgreSQL running:

```bash
# Create database and user
createdb valence
psql -d valence -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Initialize schema
psql -d valence -f src/valence/substrate/schema.sql
psql -d valence -f src/valence/substrate/procedures.sql

# Install
pip install -e .

# Set connection (if not using defaults)
export VKB_DB_HOST=localhost
export VKB_DB_NAME=valence
export VKB_DB_USER=valence
export VKB_DB_PASSWORD=your_password

# Verify
valence-mcp --health-check
```

## Configure Claude Code

### Plugin Installation

Copy the plugin to your Claude Code plugins directory:

```bash
# Create plugins dir if needed
mkdir -p ~/.claude/plugins

# Symlink the plugin
ln -s /path/to/valence/plugin ~/.claude/plugins/valence
```

Or use Claude Code directly with the plugin directory:

```bash
claude --plugin-dir /path/to/valence/plugin
```

### MCP Server

The plugin's `.mcp.json` configures a unified MCP server that provides all Valence tools. Claude Code will start it automatically when you launch with the plugin.

The server connects to PostgreSQL using environment variables:
- `VKB_DB_HOST` (default: localhost)
- `VKB_DB_PORT` (default: 5433)
- `VKB_DB_NAME` (default: valence)
- `VKB_DB_USER` (default: valence)
- `VKB_DB_PASSWORD` (default: empty)

### Embeddings (Optional)

For semantic search (finding beliefs by meaning, not just keywords):

```bash
export OPENAI_API_KEY=sk-...
```

Without this, `belief_query` (keyword search) works fine. `belief_search` (semantic search) requires embeddings.

## First Session

Start Claude Code with the Valence plugin. You'll see context injected at session start showing:
- Recent beliefs from the knowledge base
- Established patterns from past sessions
- Available skills

Just have a natural conversation. When the session ends:
1. The session-end hook fires automatically
2. If Claude called `session_end` with a summary/themes, those are auto-captured as beliefs
3. The session is closed in the database

## What Happens Automatically

### Session Start
- Creates a session record in the database
- Queries recent beliefs relevant to your project
- Queries established behavioral patterns
- Injects this context so Claude knows what you've discussed before

### During the Session
- Claude has MCP tools to query, create, and manage beliefs
- Beliefs are created explicitly when decisions are made
- Sessions, exchanges, and patterns are tracked

### Session End
- Session summary and themes are captured as beliefs (auto-capture)
- Each theme becomes its own belief for precise retrieval
- Beliefs get embeddings for semantic search (if OpenAI key is set)
- Max 10 auto-captured beliefs per session (prevents spam)

### Over Time
- Patterns emerge from repeated topics across sessions
- Beliefs accumulate, creating a knowledge base unique to you
- Confidence scores reflect reliability (dimensional: source, method, consistency, freshness, corroboration, applicability)
- Supersession chains track how knowledge evolves

## Skills Reference

Skills are invoked with `/valence:<skill-name>`:

| Skill | Description |
|-------|-------------|
| `/valence:using-valence` | Learn about the knowledge substrate |
| `/valence:query-knowledge` | Search the knowledge base |
| `/valence:capture-insight` | Store important information |
| `/valence:ingest-document` | Add documents to the substrate |
| `/valence:review-tensions` | Review and resolve contradictions |
| `/valence:status` | View knowledge base dashboard |

## MCP Tools

### Knowledge Substrate
| Tool | Description |
|------|-------------|
| `belief_query` | Search beliefs (keyword + ranking) |
| `belief_search` | Semantic search (embeddings) |
| `belief_create` | Store a new belief |
| `belief_supersede` | Update a belief with history |
| `belief_get` | Get belief details |
| `entity_get` | Get entity with beliefs |
| `entity_search` | Find entities |
| `tension_list` | List contradictions |
| `tension_resolve` | Resolve contradiction |
| `belief_corroboration` | Check corroboration |
| `trust_check` | Who to trust on a topic |
| `confidence_explain` | Explain confidence breakdown |

### Conversation Tracking
| Tool | Description |
|------|-------------|
| `session_start/end/get/list` | Manage sessions |
| `session_find_by_room` | Find by room ID |
| `exchange_add/list` | Record turns |
| `pattern_record/reinforce/list/search` | Track patterns |
| `insight_extract/list` | Extract to KB |

## Going Deeper

- **Architecture**: See `CLAUDE.md` in the repo root for full architecture documentation
- **Schema**: `src/valence/substrate/schema.sql` defines all tables
- **Confidence Model**: Beliefs have 6 confidence dimensions, not just one score
- **Federation**: Valence supports peer-to-peer knowledge sharing (advanced)
- **HTTP Server**: For remote access: `valence-server` starts on port 8420
- **Deployment**: See `infra/` for production deployment with Ansible
