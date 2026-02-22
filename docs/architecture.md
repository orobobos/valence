# Valence v2 Architecture

*Branch: `v2/knowledge-system`. Aligned with the behavioral spec (SPEC.md, 2026-02-21).*

---

## Overview

Valence is a knowledge system organized around four layers: Source, Article, Trace, and Provenance. It uses a unified inference router for all LLM operations, a mutation queue to prevent cascade storms, and a bounded memory model to keep the system from growing unboundedly.

The system is **lazy by design**: expensive operations (embedding, compilation, relationship analysis) are triggered by use, not by ingestion. A single ingested source can answer a query. No minimum data threshold is required.

---

## Four Layers

### 1. Source Layer

Sources are the raw inputs to the system. They are **immutable after ingestion** — never edited, only deleted (C10). Each source carries:

- `id` — UUID
- `content` — raw text
- `source_type` — one of: `document`, `conversation`, `web`, `code`, `observation`, `tool_output`, `user_input`
- `title`, `url` — optional metadata
- `fingerprint` — SHA-256 of content (deduplication)
- `reliability_score` — initialized from type defaults; adjusted by corroboration over time
- `created_at` — ingestion timestamp

**Reliability defaults by type:**

| Type | Default reliability |
|------|---------------------|
| document | 0.8 |
| web | 0.6 |
| conversation | 0.5 |
| code | 0.7 |
| observation | 0.6 |
| tool_output | 0.65 |
| user_input | 0.5 |

Embedding and entity extraction are deferred until the source is actually queried. Ingestion is cheap: store text, timestamp, origin, and fingerprint — nothing more.

**Key table:** `sources`

### 2. Article Layer

Articles are compiled knowledge units — summarized, right-sized, and updated through use.

**Compilation is use-driven (DR-2):** An article is created or updated when:
- A query surfaces relevant ungrouped sources (use promotes raw sources into articles)
- New source material is relevant to an existing article
- An operator explicitly triggers compilation

Articles are never compiled eagerly on ingestion. Most sources will never be compiled, and that's correct — compute follows attention.

Each article has:
- `id` — UUID (stable through mutations, per DR-3)
- `title`, `content`
- `author_type` — `system`, `operator`, or `agent`
- `confidence_score` — derived from source count, corroboration, and freshness
- `last_compiled_at`, `last_retrieved_at`
- `is_degraded` — true if compiled without full inference

**Right-sizing (C3):** When an article exceeds context window thresholds, a split is queued. When related articles are too fragmented, a merge candidate is queued. Both are deferred mutations — never nested within the triggering operation.

**Article identity through mutations (DR-3):**
- **Split**: Original article retains its ID (modified content). New article gets a new ID with provenance linking back to the split origin.
- **Merge**: New article inherits both originals' sources. Originals are archived.
- **Incremental update**: Source added to provenance with appropriate relationship type.

**Key tables:** `articles`, `article_mutations`

### 3. Trace Layer

Usage traces drive self-organization (C4). Every article retrieval is recorded.

Articles used frequently stay current and well-maintained. Articles that aren't retrieved decay in maintenance priority. Below capacity, unused articles simply deprioritize in retrieval rankings. When bounded memory capacity is reached, the lowest-scoring articles (by recency, retrieval frequency, and connection count) are evicted first (C10).

**Retrieval ranking signals:**
1. **Relevance** — semantic similarity to query
2. **Confidence** — source count, corroboration depth, provenance quality
3. **Freshness** — recency of sources and last compilation

**Key table:** `usage_traces`

### 4. Provenance Layer

Every article knows which sources built it and how. Provenance relationships are typed (C5):

| Relationship | Meaning |
|---|---|
| `originates` | Source introduced the information first captured in this article |
| `confirms` | Independent corroboration of information already in the article |
| `supersedes` | Newer source authoritatively replacing older information |
| `contradicts` | Source actively disagreeing with the article |
| `contends` | Source differing without direct contradiction — tension preserved |

**Provenance granularity (DR-1):** Tracked at the article level — each article knows which sources contributed and how. On-demand claim tracing ("where did this statement come from?") is supported via the inference layer, but exhaustive pre-computed claim-level attribution is not required.

**Contention surfacing (C7):** When sources disagree, both positions are held. Contention is surfaced at retrieval — articles with active contention carry contention metadata. Resolution is an explicit operator act (accept one position, note both as valid, or mark resolved with rationale).

**Key tables:** `article_sources`, `contentions`

---

## Inference Router

The system requires LLM capabilities for five distinct operations. All five route through a **single configured inference provider** (DR-8, DR-13).

### Task Types

**TASK_COMPILE** — synthesize multiple sources into a coherent article (highest complexity):
```
Input:  { sources: [{id, content, title, source_type}], title_hint?, max_tokens }
Output: { title, content, source_relationships: [{source_id, relationship}] }
```

**TASK_UPDATE** — incorporate new source material into an existing article:
```
Input:  { article: {id, title, content}, source: {id, content, title, source_type} }
Output: { content, relationship, changes_summary }
```

**TASK_CLASSIFY** — determine relationship type between a source and an article:
```
Input:  { article: {id, title, content}, source: {id, content, title, source_type} }
Output: { relationship, confidence: float, reasoning }
```

**TASK_CONTENTION** — assess whether a source materially disagrees with an article:
```
Input:  { article: {id, title, content}, source: {id, content, title, source_type} }
Output: { is_contention: bool, materiality: float, explanation }
```

**TASK_SPLIT** — determine the best split point for an oversized article:
```
Input:  { article: {id, title, content}, max_tokens }
Output: { split_index: int, part_a_title, part_b_title, reasoning }
```
`split_index` is a character offset into the article content.

### Schemas and Validation (DR-11)

Each task has a strict JSON schema. The router validates all LLM responses against the output schema. Extra keys are ignored; missing optional keys get defaults. Schema mismatches are caught immediately, not propagated.

### Backends

Configured via `valence config inference` or directly in `system_config`:

| Provider | Notes |
|---|---|
| `gemini` | Google Gemini 2.5 Flash via local `gemini` CLI. No API key. Default. |
| `cerebras` | OpenAI-compat API, Cerebras Cloud. US-based, ultra-low-latency for classification. |
| `ollama` | OpenAI-compat API, local Ollama. Fully offline. |

### Degraded Mode (DR-9)

When inference is unavailable:
- Compilation falls back to source concatenation
- Classification defaults to `originates`
- Contention detection is deferred
- Splits use structural boundaries (paragraph boundaries)

Outputs produced in degraded mode are flagged (`is_degraded = true`). When inference becomes available, the system automatically requeues degraded articles and relationships for recompilation via the mutation queue.

---

## Mutation Queue

Each mutation is atomic — a source update triggers at most one article update (DR-6). If that update causes the article to exceed size limits, the split is **queued** as a separate operation, not nested inline. This prevents cascade storms and makes each operation independently debuggable.

The queue executes lazily (on next use) or can be explicitly drained. Queued operations are visible and inspectable.

**Key table:** `mutation_queue`

Schema of a queue entry:
```
id          — UUID
operation   — compile | update | split | merge | classify | recompile_degraded
payload     — JSONB (operation-specific parameters)
status      — pending | running | done | failed
created_at, started_at, completed_at
error       — failure details if status=failed
```

---

## Schema Overview

20 tables (down from 78 in v1). Federation, consensus, staking, and transport tables removed.

| Table | Purpose |
|---|---|
| `sources` | Raw immutable inputs |
| `articles` | Compiled knowledge units |
| `article_sources` | Provenance links (source → article, typed relationship) |
| `article_mutations` | Mutation history (splits, merges, updates) |
| `article_entities` | Named entities extracted from articles |
| `entities` | Entity registry |
| `contentions` | Active disagreements between sources and articles |
| `mutation_queue` | Deferred operations |
| `system_config` | Key-value config (inference backend, thresholds) |
| `usage_traces` | Retrieval events for self-organization |
| `vkb_sessions` | Conversation session tracking |
| `vkb_exchanges` | Individual exchanges within sessions |
| `vkb_patterns` | Learned interaction patterns |
| `vkb_session_insights` | Per-session insight summaries |
| `belief_corroborations` | Legacy corroboration tracking (v1 compat) |
| `embedding_types` | Registered embedding model configurations |
| `embedding_coverage` | Which items have embeddings under which model |
| `tombstones` | Soft-deleted item registry (for privacy compliance) |
| `consent_records` | Data consent tracking |
| `audit_log` | Immutable audit trail |

**Extensions required:** `pgvector` (vector similarity search), `uuid-ossp` (UUID generation).

---

## API Consistency (DR-10)

All public API endpoints return a consistent envelope:

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "degraded": false
}
```

- `success` — boolean, always present
- `data` — typed payload, present on success
- `error` — string, present on failure
- `degraded` — true if output was produced in degraded inference mode

Internal functions may be synchronous where natural (pure DB operations). The public HTTP layer is uniformly async.

---

## Non-Goals (v2)

- Real-time multi-user collaboration
- Federation across instances (may be added later)
- Training pipeline / model fine-tuning
- Network protocol between instances
- Exhaustive pre-computed claim-level provenance
- MCP server as primary integration surface (MCP exists but is secondary)
