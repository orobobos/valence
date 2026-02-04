# Differential Privacy for Belief Aggregation

*Concrete epsilon recommendations and privacy budget tracking for Valence federation.*

**Status:** NORMATIVE  
**Author:** Security Subagent  
**Date:** 2026-02-04  
**Issue:** #7 - Specify differential privacy epsilon for k-anonymity

---

## Executive Summary

This document specifies the differential privacy (DP) parameters for Valence belief aggregation. It addresses the k-Anonymity Threshold Attack identified in THREAT-MODEL.md §1.3.3 by:

1. **Specifying minimum epsilon values** for different use cases
2. **Implementing temporal smoothing** to prevent membership inference
3. **Increasing k-anonymity thresholds** for sensitive federations
4. **Adding histogram suppression** for small contributor counts
5. **Implementing query rate limiting** per topic

---

## 1. Epsilon Recommendations

### 1.1 Privacy Levels

| Privacy Level | ε (epsilon) | δ (delta) | Use Case | Disclosure Risk |
|--------------|-------------|-----------|----------|-----------------|
| **MAXIMUM** | 0.1 | 10⁻⁸ | Medical, financial, legal beliefs | ~10% distinguishing advantage |
| **HIGH** | 0.5 | 10⁻⁷ | Personal opinions, sensitive topics | ~40% distinguishing advantage |
| **STANDARD** | 1.0 | 10⁻⁶ | General knowledge sharing | ~63% distinguishing advantage |
| **RELAXED** | 2.0 | 10⁻⁵ | Low-sensitivity, high-utility needs | ~86% distinguishing advantage |

**Note:** ε > 3.0 is NOT RECOMMENDED. At ε = 3.0, an adversary has ~95% advantage in distinguishing whether an individual contributed.

### 1.2 Default Configuration

```python
# MANDATORY defaults for federation aggregation
DEFAULT_EPSILON = 1.0        # Standard privacy
DEFAULT_DELTA = 1e-6         # Cryptographically small
MIN_K_ANONYMITY = 5          # Minimum contributors for any aggregate
SENSITIVE_K_ANONYMITY = 10   # For sensitive federations

# Epsilon bounds
MIN_EPSILON = 0.01           # Anything lower provides negligible utility
MAX_EPSILON = 3.0            # Anything higher provides negligible privacy
```

### 1.3 Per-Federation Overrides

Federations MAY configure stricter (lower) epsilon:

```typescript
interface FederationPrivacyConfig {
  // Required
  epsilon: float              // MUST be in [0.01, 3.0], default 1.0
  delta: float                // MUST be < 10⁻⁴, default 10⁻⁶
  
  // k-anonymity
  min_contributors: uint8     // MUST be >= 5, default 5
  sensitive_domain: boolean   // If true, min_contributors = max(config, 10)
  
  // Budget
  daily_epsilon_budget: float // Default: 10.0 (10 queries at ε=1.0)
  
  // Temporal
  membership_smoothing_hours: uint16  // Default: 24
}
```

---

## 2. Privacy Budget Tracking

### 2.1 Composition Theorem

Sequential queries compose linearly under basic composition:
- Query 1 with ε₁ + Query 2 with ε₂ = Total privacy loss of ε₁ + ε₂

For advanced composition (tighter bounds with many queries), use:
- Total ε ≤ √(2k × ln(1/δ')) × ε₀ + k × ε₀ × (e^ε₀ - 1)

Where k = number of queries, ε₀ = per-query epsilon, δ' = additional delta.

### 2.2 Budget Implementation

```python
@dataclass
class PrivacyBudget:
    """Track cumulative privacy loss."""
    
    federation_id: UUID
    
    # Daily budget (resets every 24 hours)
    daily_epsilon_budget: float = 10.0
    daily_delta_budget: float = 1e-4
    
    # Current spend
    spent_epsilon: float = 0.0
    spent_delta: float = 0.0
    
    # Per-topic tracking (prevents targeted attacks)
    topic_spend: dict[str, TopicBudget] = field(default_factory=dict)
    
    # Reset tracking
    period_start: datetime = field(default_factory=datetime.utcnow)
    budget_period_hours: int = 24
    
    def can_query(self, epsilon: float, delta: float, topic_hash: str) -> tuple[bool, str]:
        """Check if budget allows this query."""
        self._maybe_reset()
        
        # Global budget check
        if self.spent_epsilon + epsilon > self.daily_epsilon_budget:
            return False, "daily_epsilon_exhausted"
        if self.spent_delta + delta > self.daily_delta_budget:
            return False, "daily_delta_exhausted"
        
        # Per-topic rate limit (max 3 queries per topic per day)
        topic = self.topic_spend.get(topic_hash)
        if topic and topic.query_count >= 3:
            return False, "topic_rate_limited"
        
        return True, "ok"
    
    def consume(self, epsilon: float, delta: float, topic_hash: str) -> None:
        """Record budget consumption."""
        self.spent_epsilon += epsilon
        self.spent_delta += delta
        
        if topic_hash not in self.topic_spend:
            self.topic_spend[topic_hash] = TopicBudget()
        self.topic_spend[topic_hash].query_count += 1
        self.topic_spend[topic_hash].epsilon_spent += epsilon
    
    def remaining_epsilon(self) -> float:
        """Get remaining epsilon budget."""
        self._maybe_reset()
        return max(0, self.daily_epsilon_budget - self.spent_epsilon)
    
    def _maybe_reset(self) -> None:
        """Reset budget if period has elapsed."""
        now = datetime.utcnow()
        if (now - self.period_start).total_seconds() > self.budget_period_hours * 3600:
            self.spent_epsilon = 0.0
            self.spent_delta = 0.0
            self.topic_spend.clear()
            self.period_start = now


@dataclass
class TopicBudget:
    """Per-topic budget tracking."""
    query_count: int = 0
    epsilon_spent: float = 0.0
    last_query: datetime = field(default_factory=datetime.utcnow)
```

### 2.3 Query Rate Limiting

To prevent targeted inference attacks:

| Scope | Rate Limit | Purpose |
|-------|------------|---------|
| **Per-topic** | 3 queries/day | Prevent belief enumeration |
| **Per-federation** | 100 queries/day | Global abuse prevention |
| **Per-requester** | 20 queries/hour | Slow down adversaries |

---

## 3. Temporal Smoothing

### 3.1 The Problem

Immediate reflection of membership changes enables inference:

```
t=0: Query "Topic X" → 5 contributors, confidence 0.8
t=1: Alice leaves federation
t=2: Query "Topic X" → 4 contributors, confidence hidden
Inference: Alice held beliefs about Topic X
```

### 3.2 The Solution: Delayed Membership Reflection

Aggregate statistics MUST NOT immediately reflect membership changes:

```python
MEMBERSHIP_SMOOTHING_HOURS = 24  # Default: 24 hours

def compute_effective_members(
    federation: Federation,
    topic: str,
    query_time: datetime
) -> list[Member]:
    """Get members whose contributions should be included."""
    effective_members = []
    
    for member in federation.all_members:
        # Include if currently active
        if member.status == MemberStatus.ACTIVE:
            effective_members.append(member)
            continue
        
        # Include recently departed (within smoothing window)
        if member.departed_at:
            hours_since_departure = (query_time - member.departed_at).total_seconds() / 3600
            if hours_since_departure < MEMBERSHIP_SMOOTHING_HOURS:
                # Still include their contributions (with probability)
                # Probability decreases linearly over smoothing period
                inclusion_probability = 1 - (hours_since_departure / MEMBERSHIP_SMOOTHING_HOURS)
                if random.random() < inclusion_probability:
                    effective_members.append(member)
    
    return effective_members
```

### 3.3 New Member Smoothing

Similarly, new members' contributions are phased in:

```python
def get_contribution_weight(member: Member, query_time: datetime) -> float:
    """Get contribution weight based on membership duration."""
    if member.joined_at is None:
        return 1.0  # Founding member
    
    hours_since_join = (query_time - member.joined_at).total_seconds() / 3600
    
    if hours_since_join < MEMBERSHIP_SMOOTHING_HOURS:
        # Ramp up contribution weight over smoothing period
        return hours_since_join / MEMBERSHIP_SMOOTHING_HOURS
    
    return 1.0
```

---

## 4. Histogram Suppression

### 4.1 The Problem

Confidence distribution histograms can leak information with small k:

```json
{
  "contributor_count": 5,
  "confidence_distribution": {
    "0.0-0.2": 0,
    "0.2-0.4": 1,
    "0.4-0.6": 2,
    "0.6-0.8": 1,
    "0.8-1.0": 1
  }
}
```

With only 5 contributors, the histogram effectively deanonymizes confidence levels.

### 4.2 The Solution: Threshold-Based Suppression

```python
HISTOGRAM_SUPPRESSION_THRESHOLD = 20

def build_aggregate_response(
    aggregate: Aggregate,
    privacy_params: PrivacyParameters
) -> dict:
    """Build privacy-preserving aggregate response."""
    response = {
        "collective_confidence": add_laplace_noise(
            aggregate.mean_confidence,
            sensitivity=1.0,
            epsilon=privacy_params.epsilon
        ),
        "contributor_count": add_laplace_noise(
            aggregate.contributor_count,
            sensitivity=1,
            epsilon=privacy_params.epsilon
        ),
    }
    
    # Only include histogram if sufficient contributors
    if aggregate.contributor_count >= HISTOGRAM_SUPPRESSION_THRESHOLD:
        response["confidence_distribution"] = build_noisy_histogram(
            aggregate.confidences,
            epsilon=privacy_params.epsilon / 5  # Split budget across bins
        )
    
    return response


def build_noisy_histogram(
    values: list[float],
    epsilon: float,
    bins: int = 5
) -> dict[str, int]:
    """Build histogram with DP noise."""
    # Create bins
    bin_edges = [i / bins for i in range(bins + 1)]
    counts = [0] * bins
    
    for v in values:
        bin_idx = min(int(v * bins), bins - 1)
        counts[bin_idx] += 1
    
    # Add Laplace noise to each bin
    noisy_counts = [
        max(0, round(c + np.random.laplace(0, 1.0 / epsilon)))
        for c in counts
    ]
    
    return {
        f"{bin_edges[i]:.1f}-{bin_edges[i+1]:.1f}": noisy_counts[i]
        for i in range(bins)
    }
```

---

## 5. Sensitive Federation Handling

### 5.1 Sensitive Domain Detection

Certain domains require elevated privacy:

```python
SENSITIVE_DOMAINS = [
    "health", "medical", "mental_health",
    "finance", "banking", "investments",
    "legal", "law", "criminal",
    "politics", "religion", "sexuality",
    "employment", "salary", "hr",
]

def is_sensitive_federation(federation: Federation) -> bool:
    """Check if federation handles sensitive topics."""
    # Explicit flag
    if federation.config.get("sensitive", False):
        return True
    
    # Check domains
    for domain in federation.domains:
        domain_lower = domain.lower()
        if any(s in domain_lower for s in SENSITIVE_DOMAINS):
            return True
    
    return False
```

### 5.2 Elevated Privacy Parameters

```python
def get_privacy_params(federation: Federation) -> PrivacyParameters:
    """Get privacy parameters for federation."""
    base_params = federation.privacy_config or DEFAULT_PRIVACY_PARAMS
    
    if is_sensitive_federation(federation):
        return PrivacyParameters(
            epsilon=min(base_params.epsilon, 0.5),  # Force stricter
            delta=min(base_params.delta, 1e-7),
            min_contributors=max(base_params.min_contributors, 10),  # k >= 10
            histogram_threshold=30,  # Higher threshold
            temporal_smoothing_hours=48,  # Longer smoothing
        )
    
    return base_params
```

---

## 6. Noise Mechanisms

### 6.1 Laplace Mechanism (Default)

For numeric queries with bounded sensitivity:

```python
def add_laplace_noise(
    true_value: float,
    sensitivity: float,
    epsilon: float
) -> float:
    """Add Laplace noise for (ε, 0)-differential privacy."""
    scale = sensitivity / epsilon
    noise = np.random.laplace(0, scale)
    return true_value + noise
```

**Properties:**
- Pure DP (δ = 0)
- Unbounded noise (can produce outliers)
- Best for bounded numeric queries

### 6.2 Gaussian Mechanism (Alternative)

For queries requiring bounded noise:

```python
def add_gaussian_noise(
    true_value: float,
    sensitivity: float,
    epsilon: float,
    delta: float
) -> float:
    """Add Gaussian noise for (ε, δ)-differential privacy."""
    sigma = sensitivity * math.sqrt(2 * math.log(1.25 / delta)) / epsilon
    noise = np.random.normal(0, sigma)
    return true_value + noise
```

**Properties:**
- Approximate DP (δ > 0)
- Bounded noise (tighter concentration)
- Better for composition

### 6.3 Mechanism Selection

| Use Case | Mechanism | Reason |
|----------|-----------|--------|
| Single numeric query | Laplace | Pure DP, simple |
| Many queries (composition) | Gaussian | Better bounds |
| Histograms | Laplace per bin | Standard practice |
| Count queries | Laplace or Geometric | Discrete output |

---

## 7. Implementation Checklist

### Required for Issue #7 Resolution

- [x] **Specify minimum epsilon** — ε ∈ [0.01, 3.0], default 1.0
- [x] **Add temporal smoothing** — 24-hour membership reflection delay
- [x] **Increase default k** — k=10 for sensitive federations
- [x] **Remove histogram below threshold** — Suppress when contributor_count < 20
- [x] **Add query rate limiting** — 3/topic/day, 100/federation/day

### Implementation Components

1. **PrivacyBudget class** — Track cumulative epsilon/delta spend
2. **TopicRateLimiter** — Per-topic query limits
3. **MembershipSmoother** — Delayed membership reflection
4. **HistogramSuppressor** — Conditional histogram inclusion
5. **SensitivityDetector** — Auto-detect sensitive federations

---

## 8. Security Considerations

### 8.1 Attack Mitigations

| Attack | Mitigation | Residual Risk |
|--------|------------|---------------|
| k-Anonymity threshold | k ≥ 5 (10 for sensitive) | Low |
| Membership inference | 24h temporal smoothing | Low |
| Histogram fingerprinting | Suppress below 20 contributors | Low |
| Query accumulation | Daily budget reset | Medium (patient attacker) |
| Topic enumeration | 3 queries/topic/day | Low |

### 8.2 Known Limitations

1. **Reconstruction attacks**: With enough queries over time, an adversary may still infer information. Budget tracking limits but doesn't eliminate this.

2. **Collusion**: If k-1 of k contributors collude, they can infer the k-th contributor's beliefs. k=10 provides better protection than k=5.

3. **Side channels**: Timing, response size, and other metadata may leak information. This spec doesn't address network-level privacy.

---

## 9. References

- [Dwork & Roth, 2014] "The Algorithmic Foundations of Differential Privacy"
- [Apple, 2017] "Learning with Privacy at Scale"
- [Google, 2014] "RAPPOR: Randomized Aggregatable Privacy-Preserving Ordinal Response"
- THREAT-MODEL.md §1.3.3 — k-Anonymity Threshold Attack

---

*"Privacy is protection from arbitrary information collection, regardless of whether that information is embarrassing or not."*
— Bruce Schneier
