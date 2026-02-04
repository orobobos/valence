# External Source Verification for L4 Elevation

*"Trust but verify—especially when it comes to external evidence."*

---

## Overview

This specification defines how Valence verifies external sources cited as evidence for L4 (Communal Knowledge) elevation. Per THREAT-MODEL.md §1.4.2, the independence oracle can be gamed without proper external verification—coordinated actors can cite fabricated sources that appear independent but trace back to a common origin.

**Core principle**: L4 elevation requires at least one machine-verifiable external source that:
1. **Exists**: URL resolves, DOI is valid, etc.
2. **Supports the claim**: Content semantically matches the belief
3. **Is reliable**: Source category and history meet quality thresholds

---

## 1. External Source Types

### 1.1 Supported Identifiers

| Identifier | Format | Verification Method |
|------------|--------|---------------------|
| URL | `https://...` | HTTP liveness check + content fetch |
| DOI | `10.xxxx/...` | doi.org API + CrossRef metadata |
| ISBN | `978-x-xxxx-xxxx-x` | Library APIs (OCLC, OpenLibrary) |
| arXiv ID | `arXiv:xxxx.xxxxx` | arXiv API |
| PubMed ID | `PMID:xxxxxxxx` | NCBI E-utilities |

### 1.2 Source Categories

Sources are classified into categories with baseline reliability scores:

| Category | Base Reliability | Examples |
|----------|-----------------|----------|
| `academic_journal` | 0.90 | Nature, Science, peer-reviewed papers |
| `academic_preprint` | 0.75 | arXiv, bioRxiv, SSRN |
| `government` | 0.80 | .gov sites, official statistics |
| `news_major` | 0.70 | Reuters, AP, BBC |
| `news_regional` | 0.55 | Regional newspapers |
| `encyclopedia` | 0.65 | Wikipedia, Britannica |
| `technical_docs` | 0.85 | RFCs, W3C specs |
| `social_verified` | 0.50 | Verified Twitter/X accounts |
| `corporate` | 0.55 | Company press releases |
| `personal_blog` | 0.35 | Personal websites, blogs |
| `unknown` | 0.30 | Unclassified sources |

---

## 2. Trusted Source Registry

### 2.1 Purpose

The Trusted Source Registry maintains:
- **Trusted domains**: Known reliable sources with category overrides
- **DOI prefixes**: Academic publisher identifiers
- **Blocklist**: Known unreliable or malicious domains

### 2.2 Registry Schema

```typescript
TrustedDomain {
  domain: string              // e.g., "nature.com", ".gov"
  category: SourceCategory
  reliability_override?: float  // Override category default
  
  // Access rules
  require_https: boolean
  allowed_paths?: string[]    // Regex patterns
  blocked_paths?: string[]    // Regex patterns
  
  // Metadata
  added_at: timestamp
  added_by?: DID              // Admin who added
  notes?: string
}

DOIPrefix {
  prefix: string              // e.g., "10.1038" for Nature
  publisher: string
  category: SourceCategory
  reliability_override?: float
  known_retraction_policy: boolean
}
```

### 2.3 Default Trusted Sources

The registry ships with defaults:

**Academic/Research:**
- `doi.org` — DOI resolver
- `arxiv.org` — Physics/CS/Math preprints
- `pubmed.ncbi.nlm.nih.gov` — Biomedical literature
- `semanticscholar.org` — AI-curated papers

**Government:**
- `.gov` (US), `.gov.uk` (UK), `europa.eu` (EU)

**Technical:**
- `rfc-editor.org`, `w3.org`, `ietf.org`

**Major News:**
- `reuters.com`, `apnews.com`, `bbc.com`

---

## 3. Verification Workflow

### 3.1 Liveness Check

Before accepting a source, verify it exists and is accessible:

```
Input: URL, DOI, or ISBN
  │
  ├─ URL:
  │    ├─ Check blocklist
  │    ├─ HTTP HEAD request (or GET if needed)
  │    ├─ Follow redirects (max 5)
  │    ├─ Verify final URL is not blocklisted
  │    └─ Return: status, content-type, size
  │
  ├─ DOI:
  │    ├─ Query doi.org/api/handles/{doi}
  │    ├─ Resolve to URL
  │    ├─ Check Retraction Watch database
  │    └─ Return: metadata, retraction status
  │
  └─ ISBN:
       ├─ Query OpenLibrary API
       ├─ Verify book exists
       └─ Return: title, authors, publication date
```

**Liveness statuses:**
- `live` — Source accessible
- `dead` — 404 or similar
- `timeout` — Request timed out
- `blocked` — Access denied (paywall, geo-restriction)
- `redirect` — Redirected to different content (suspicious)

### 3.2 Content Matching

Verify the source actually supports the belief:

```
Input: belief_content, fetched_source_content
  │
  ├─ Generate embeddings:
  │    ├─ belief_embedding = embed(belief_content)
  │    └─ source_embedding = embed(source_content)
  │
  ├─ Compute similarity:
  │    └─ similarity = cosine(belief_embedding, source_embedding)
  │
  ├─ Extract supporting passages:
  │    ├─ Chunk source content
  │    ├─ Find chunks with highest similarity
  │    └─ Return top 3 passages
  │
  └─ Return: similarity_score, matched_passages
```

**Thresholds:**
- `< 0.65` — FAIL: Content doesn't support claim
- `0.65-0.85` — PASS: Moderate support
- `> 0.85` — STRONG: Clear support

### 3.3 Reliability Scoring

Compute overall reliability from multiple factors:

```python
def compute_reliability(verification) -> SourceReliabilityScore:
    # Base category score
    category_score = verification.category.base_reliability
    
    # Registry bonus (if in trusted registry)
    registry_bonus = 0.1 if in_registry(verification.source) else 0.0
    
    # Liveness (binary)
    liveness_score = 1.0 if verification.liveness.is_live else 0.0
    
    # Content match
    content_match_score = verification.content_match.similarity_score
    
    # Freshness (based on source date)
    if source_date:
        days_old = (now - source_date).days
        if days_old > 730:  # 2 years
            freshness_score = 0.6
            staleness_penalty = 0.2
        elif days_old < 30:
            freshness_score = 1.1  # Recent bonus
        else:
            freshness_score = 1.0
    
    # Weighted combination
    overall = (
        0.25 * category_score +
        0.20 * liveness_score +
        0.35 * content_match_score +
        0.10 * freshness_score +
        0.10 * (1.0 + registry_bonus)
    ) - penalties
    
    return clamp(overall, 0.0, 1.0)
```

---

## 4. L4 Elevation Requirements

### 4.1 Minimum Requirements

For a belief to be eligible for L4 elevation, it MUST have:

| Requirement | Threshold | Rationale |
|-------------|-----------|-----------|
| External sources | ≥ 1 | At least one machine-verifiable source |
| Verified sources | ≥ 1 | At least one source passes verification |
| Best reliability | ≥ 0.50 | Source meets quality threshold |
| Best content match | ≥ 0.65 | Source actually supports claim |

### 4.2 Requirements Check

```typescript
L4SourceRequirements {
  belief_id: UUID
  
  // Status
  has_external_sources: boolean
  has_verified_sources: boolean
  meets_reliability_threshold: boolean
  meets_content_match_threshold: boolean
  all_requirements_met: boolean
  
  // Counts
  total_sources: int
  verified_sources: int
  failed_sources: int
  
  // Best source
  best_source_id: UUID
  best_reliability_score: float
  best_content_match_score: float
  
  // Issues (if requirements not met)
  issues: string[]
}
```

### 4.3 Integration with Elevation

The L4 elevation workflow includes external source checks:

```
Belief nominated for L4 elevation
  │
  ├─ Check existing requirements:
  │    ├─ Cross-domain corroboration ✓
  │    ├─ Independence score > 0.7 ✓
  │    ├─ Byzantine quorum ready ✓
  │    └─ Minimum age (7 days) ✓
  │
  ├─ NEW: External source verification:
  │    ├─ Fetch external sources cited in evidence
  │    ├─ Run verification workflow for each
  │    ├─ Check L4SourceRequirements
  │    │
  │    ├─ If all_requirements_met:
  │    │    └─ Continue to elevation
  │    │
  │    └─ If NOT met:
  │         ├─ Record issues
  │         ├─ Notify belief holder
  │         └─ Defer elevation
  │
  └─ Proceed with Byzantine consensus vote
```

---

## 5. Data Structures

### 5.1 ExternalSourceVerification

```typescript
ExternalSourceVerification {
  id: UUID
  belief_id: UUID
  
  // Source identifiers
  url?: string
  doi?: string
  isbn?: string
  citation?: string  // Human-readable
  
  // Verification results
  status: VerificationStatus  // pending | verified | failed_* | blocked
  liveness?: LivenessCheckResult
  content_match?: ContentMatchResult
  doi_verification?: DOIVerificationResult
  reliability?: SourceReliabilityScore
  
  // Classification
  category: SourceCategory
  
  // Content snapshot
  content_hash?: string     // SHA-256 of fetched content
  archived_at?: timestamp
  archive_url?: string      // Archive.org backup
  
  // Timing
  created_at: timestamp
  verified_at?: timestamp
  expires_at?: timestamp    // When to re-verify
}
```

### 5.2 LivenessCheckResult

```typescript
LivenessCheckResult {
  status: SourceLivenessStatus  // live | dead | timeout | blocked | redirect
  http_status?: int
  final_url?: string            // After redirects
  content_type?: string
  content_length?: int
  checked_at: timestamp
  error_message?: string
  response_time_ms?: int
}
```

### 5.3 ContentMatchResult

```typescript
ContentMatchResult {
  similarity_score: float       // 0.0-1.0
  matched_passages: string[]    // Supporting excerpts
  method: string                // 'semantic' | 'keyword'
  analyzed_at: timestamp
}
```

### 5.4 SourceReliabilityScore

```typescript
SourceReliabilityScore {
  overall: float                // 0.0-1.0 final score
  
  // Components
  category_score: float
  liveness_score: float
  content_match_score: float
  freshness_score: float
  registry_score: float         // Bonus if in trusted registry
  
  // Penalties
  staleness_penalty: float
  redirect_penalty: float
}
```

---

## 6. Security Considerations

### 6.1 Threats Mitigated

This specification addresses:

1. **Fabricated sources**: Liveness checks catch non-existent URLs/DOIs
2. **Irrelevant sources**: Content matching ensures source supports claim
3. **Low-quality sources**: Reliability scoring filters unreliable sources
4. **Coordinated citation**: Multiple agents citing same source doesn't multiply independence

### 6.2 Remaining Risks

| Risk | Mitigation | Residual |
|------|------------|----------|
| Temporary source availability | Caching + archive fallback | Low |
| Source content changes | Content hashing + periodic re-verification | Medium |
| Sophisticated fabrication | NLP matching + human review for disputes | Medium |
| Blocklist evasion | Community reporting + heuristics | Low |

### 6.3 Rate Limiting

To prevent abuse:
- Max 10 verifications per source per hour
- Max 20 sources per belief
- Liveness cache TTL: 24 hours
- Content match computed once per source+belief pair

---

## 7. API Reference

### 7.1 Create Verification

```python
verification = service.create_verification(
    belief_id=belief_uuid,
    url="https://example.com/article",
    doi="10.1234/example",
    citation="Smith et al., 2024"
)
```

### 7.2 Run Full Verification

```python
result = service.verify_source(
    verification_id=verification.id,
    belief_content="The claim being verified"
)
# Returns: ExternalSourceVerification with all results populated
```

### 7.3 Check L4 Requirements

```python
requirements = service.check_l4_requirements(
    belief_id=belief_uuid,
    belief_content="The belief content"
)
if requirements.all_requirements_met:
    # Proceed with L4 elevation
else:
    # Handle issues: requirements.issues
```

### 7.4 Convenience Function

```python
from valence.core.external_sources import check_belief_l4_readiness

result = check_belief_l4_readiness(
    belief_id=belief_uuid,
    belief_content="The belief content",
    sources=[
        {"url": "https://nature.com/article"},
        {"doi": "10.1038/example"},
    ]
)
```

---

## 8. Implementation Notes

### 8.1 Dependencies

- **HTTP client**: For liveness checks (aiohttp recommended)
- **Embedding model**: For semantic similarity (sentence-transformers or OpenAI)
- **DOI resolver**: CrossRef API client
- **Database**: PostgreSQL for persistence

### 8.2 Configuration

Environment variables:
```bash
VALENCE_LIVENESS_TIMEOUT=30        # Seconds
VALENCE_MAX_CONTENT_SIZE=10485760  # 10MB
VALENCE_MIN_CONTENT_SIMILARITY=0.65
VALENCE_MIN_SOURCE_RELIABILITY=0.5
```

### 8.3 Caching Strategy

- Liveness results: 24-hour TTL
- Content hashes: Permanent (for change detection)
- Reliability scores: Re-compute on source metadata change
- Registry: In-memory with periodic DB sync

---

## References

- [THREAT-MODEL.md](../../security/THREAT-MODEL.md) §1.4.2 — Independence Oracle Manipulation
- [SPEC.md](./SPEC.md) — Consensus Mechanism Specification
- [NODE-SELECTION.md](./NODE-SELECTION.md) — Validator Selection
- [CrossRef API](https://api.crossref.org) — DOI metadata
- [Retraction Watch](https://retractionwatch.com) — Academic retractions database
