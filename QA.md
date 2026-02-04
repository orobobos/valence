# Valence QA Strategy

*Quality Assurance Infrastructure and Testing Strategy*

---

## Overview

Valence uses **specification-driven development** where specs in `spec/components/` are the source of truth. Tests verify that implementations conform to specifications, not the other way around.

This document outlines:
1. Testing strategy and philosophy
2. Test suite organization
3. Coverage goals
4. Spec-to-test mapping

---

## 1. Testing Philosophy

### Specs are Truth

- **Specs define behavior** — If there's a conflict between spec and implementation, the spec wins
- **Tests verify conformance** — Tests check implementation against spec, not just "code works"
- **Gaps are visible** — Missing spec coverage should be tracked and prioritized

### Testing Pyramid

```
         ╱╲
        ╱  ╲           Spec Compliance Tests
       ╱────╲          (Does impl match spec?)
      ╱      ╲
     ╱────────╲        Integration Tests
    ╱          ╲       (Do components work together?)
   ╱────────────╲
  ╱              ╲     Unit Tests
 ╱────────────────╲    (Do individual functions work?)
```

---

## 2. Test Suite Organization

```
tests/
├── conftest.py              # Global fixtures
├── core/                    # Unit tests for core modules
│   ├── test_models.py
│   ├── test_db.py
│   ├── test_health.py
│   └── ...
├── embeddings/              # Embedding service tests
├── mcp/                     # MCP server tests  
├── agents/                  # Agent tests (Matrix, etc.)
├── integration/             # Cross-component integration tests
└── spec_compliance/         # NEW: Spec conformance tests
    ├── conftest.py          # Spec-testing fixtures
    ├── test_belief_schema.py
    ├── test_confidence_vectors.py
    ├── test_trust_graph.py
    ├── test_federation_layer.py
    ├── test_query_protocol.py
    ├── test_consensus_mechanism.py
    ├── test_identity_crypto.py
    ├── test_verification_protocol.py
    ├── test_resilient_storage.py
    ├── test_incentive_system.py
    └── test_api_integration.py
```

---

## 3. Spec-to-Test Mapping

| Spec Component | Test File | Implementation | Priority |
|----------------|-----------|----------------|----------|
| `belief-schema` | `test_belief_schema.py` | `schema.sql`, `core/models.py` | **P0** |
| `confidence-vectors` | `test_confidence_vectors.py` | `core/confidence.py` | **P0** |
| `trust-graph` | `test_trust_graph.py` | `federation/trust.py` | P1 |
| `federation-layer` | `test_federation_layer.py` | `federation/` | P1 |
| `query-protocol` | `test_query_protocol.py` | `vkb/`, `mcp/` | P1 |
| `consensus-mechanism` | `test_consensus_mechanism.py` | TBD | P2 |
| `identity-crypto` | `test_identity_crypto.py` | TBD | P2 |
| `verification-protocol` | `test_verification_protocol.py` | TBD | P2 |
| `resilient-storage` | `test_resilient_storage.py` | `substrate/` | P2 |
| `incentive-system` | `test_incentive_system.py` | TBD | P3 |
| `api-integration` | `test_api_integration.py` | `server/` | P1 |

### Priority Definitions

- **P0**: Core functionality, must pass before any release
- **P1**: Important features, should pass for MVP
- **P2**: Secondary features, can have known gaps initially
- **P3**: Future/experimental features

---

## 4. Spec Compliance Test Categories

Each spec compliance test file should verify:

### 4.1 Schema Compliance
- Required fields exist
- Field types match spec
- Constraints are enforced
- Default values match spec

### 4.2 Behavioral Compliance
- Operations behave as specified
- Edge cases are handled per spec
- Error conditions produce specified behavior

### 4.3 Contract Compliance
- API signatures match spec
- Return types match spec
- Invariants are maintained

---

## 5. Coverage Goals

### Phase 1 (Current)
- [ ] 100% schema compliance for `belief-schema`
- [ ] 100% schema compliance for `confidence-vectors`
- [ ] Basic unit test coverage for core modules

### Phase 2
- [ ] All P0/P1 specs have compliance tests
- [ ] Integration tests for belief lifecycle
- [ ] 70% line coverage on core/

### Phase 3
- [ ] All specs have compliance tests
- [ ] Federation protocol testing
- [ ] 80% line coverage overall

---

## 6. Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/core tests/embeddings tests/mcp tests/agents

# Spec compliance only
pytest tests/spec_compliance

# Specific spec
pytest tests/spec_compliance/test_belief_schema.py

# With coverage
pytest --cov=src/valence --cov-report=html
```

---

## 7. Adding Spec Compliance Tests

When adding tests for a spec:

1. **Read the spec carefully** — Extract testable requirements
2. **Create test file** — `tests/spec_compliance/test_{component}.py`
3. **Structure by spec section** — Use test classes matching spec sections
4. **Reference spec in docstrings** — Include spec section references
5. **Test positive AND negative cases** — Verify constraints reject bad data

### Example Test Structure

```python
"""Spec compliance tests for belief-schema.

Reference: spec/components/belief-schema/SPEC.md
"""

class TestBeliefCoreStructure:
    """Tests for SPEC Section 1.1: Belief"""
    
    def test_belief_has_required_fields(self):
        """Verify all required fields from spec exist in schema."""
        ...

class TestConfidenceVector:
    """Tests for SPEC Section 1.2: ConfidenceVector"""
    ...
```

---

## 8. Known Gaps

| Gap | Impact | Notes |
|-----|--------|-------|
| `holder_id` → `source_id` | Minor | Spec says `holder_id`, schema uses `source_id` (acceptable for v1) |
| No `visibility` column | Moderate | Spec defines visibility enum, schema doesn't have column yet |
| No `derivation` table | Moderate | Spec has rich Derivation model, schema stores in `sources` table |
| `domains` vs `domain_path` | Minor | Spec says `domains[]`, schema uses `domain_path[]` (naming only) |

---

## 9. Future Improvements

- [ ] Automated spec→test stub generation
- [ ] Spec coverage reporting (which spec sections have tests)
- [ ] Property-based testing for invariants
- [ ] Mutation testing for critical paths
- [ ] Continuous spec compliance in CI

---

*Last updated: 2026-02-03*
