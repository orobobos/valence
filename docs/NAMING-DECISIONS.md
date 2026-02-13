# Naming Decisions: Spec vs Implementation

This document records deliberate naming differences between Valence specs and the implemented code, with rationale for each decision.

## Summary

| # | Spec Name | Code Name | Type | Rationale |
|---|-----------|-----------|------|-----------|
| 1 | `holder_id` | `source_id` | Semantic shift | Spec refers to the agent holding the belief; code tracks external sources instead |
| 2 | `domains[]` | `domain_path[]` | Naming convention | Code name is more explicit about hierarchical path semantics |
| 3 | `visibility` (3 values) | `visibility` (4 values) | Extended enum | Code adds `trusted` between `private` and `federated` |
| 4 | Full dimension names | Abbreviated column names | Naming convention | Column names shortened; `v_beliefs_full` view exposes spec names |

---

## 1. `holder_id` vs `source_id`

**Spec:** `holder_id: UUID` — The agent who holds/created the belief (spec/components/belief-schema/SPEC.md)

**Code:** `source_id UUID REFERENCES sources(id)` — A reference to the external source of information

**Decision:** Accept for v1. The spec's `holder_id` implies per-agent belief ownership in a multi-agent system. The current implementation is single-agent (personal knowledge substrate), so `source_id` tracks provenance (where the information came from) rather than ownership. When multi-agent support is added, `holder_id` should be introduced as a separate column.

**Impact:** Low — does not affect current single-user functionality.

---

## 2. `domains` vs `domain_path`

**Spec:** `domains: string[]` — Categorical tags for the belief

**Code:** `domain_path TEXT[] NOT NULL DEFAULT '{}'` — Hierarchical domain classification

**Decision:** Keep `domain_path` in code. The name better communicates that values are hierarchical paths (e.g., `tech/ai/llm`) rather than flat tags. The spec's shorter `domains` is fine for documentation. The underlying data structure and behavior are identical.

**Impact:** None — purely cosmetic naming difference.

---

## 3. Visibility Enum Values

**Spec:** 3 values — `private`, `federated`, `public`

**Code:** 4 values — `private`, `trusted`, `federated`, `public`

```sql
CONSTRAINT beliefs_valid_visibility CHECK (
    visibility IN ('private', 'trusted', 'federated', 'public')
)
```

**Decision:** Keep the additional `trusted` level. It provides a useful intermediate between fully private and open federation — beliefs visible only to trusted peers without full federation propagation. The spec should be updated to include this value.

**Impact:** Low — additional granularity is backward-compatible with spec consumers.

---

## 4. Confidence Dimension Column Names

**Spec:**
- `source_reliability`
- `method_quality`
- `internal_consistency`
- `temporal_freshness`
- `corroboration`
- `domain_applicability`

**Code (columns):**
- `confidence_source`
- `confidence_method`
- `confidence_consistency`
- `confidence_freshness`
- `confidence_corroboration`
- `confidence_applicability`

**Decision:** Keep abbreviated column names for database ergonomics. The `v_beliefs_full` database view translates back to full spec names in a JSONB object, so API consumers see the spec-compliant names.

**Impact:** None — view layer handles translation.

---

## QA.md Status

The project QA.md (line 195-200) documents these gaps. Note that the QA.md entry about "No visibility column" is outdated — the column exists but with 4 values instead of the spec's 3. QA.md should be updated accordingly.
