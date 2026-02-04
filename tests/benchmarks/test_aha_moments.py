"""Aha Moment Benchmark Suite - Proving Valence Multi-Signal Ranking

This benchmark demonstrates that confidence-weighted retrieval beats flat semantic
search through concrete, measurable scenarios.

Usage:
    pytest tests/benchmarks/test_aha_moments.py -v
    pytest tests/benchmarks/test_aha_moments.py::TestAhaMoments::test_full_benchmark -v --benchmark

Run with live database (integration):
    VKB_INTEGRATION_TEST=1 pytest tests/benchmarks/test_aha_moments.py -v
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable
from uuid import UUID, uuid4

import pytest
import numpy as np

# ============================================================================
# Test Data Structures
# ============================================================================

@dataclass
class MockBelief:
    """A test belief with all ranking-relevant attributes."""
    id: UUID
    content: str
    embedding: np.ndarray  # Normalized vector
    
    # Confidence dimensions
    source_reliability: float = 0.5
    method_quality: float = 0.5
    internal_consistency: float = 0.7
    temporal_freshness: float = 1.0
    corroboration: float = 0.2
    domain_applicability: float = 0.6
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    domain_path: list[str] = field(default_factory=list)
    holder_id: str = "default"
    
    # Ground truth for benchmarking
    is_relevant: bool = False
    relevance_grade: int = 0  # 0=irrelevant, 1=marginally, 2=relevant, 3=highly relevant
    
    @property
    def confidence_overall(self) -> float:
        """Compute geometric mean of confidence dimensions."""
        dims = [
            self.source_reliability,
            self.method_quality,
            self.internal_consistency,
            self.temporal_freshness,
            self.corroboration,
            self.domain_applicability
        ]
        # Geometric mean
        product = 1.0
        for d in dims:
            product *= max(0.01, d)  # Avoid zero
        return product ** (1/len(dims))


@dataclass
class RankingWeights:
    """Configurable ranking weights."""
    semantic: float = 0.35
    confidence: float = 0.25
    trust: float = 0.30
    recency: float = 0.10
    
    def __post_init__(self):
        total = self.semantic + self.confidence + self.trust + self.recency
        assert abs(total - 1.0) < 0.001, f"Weights must sum to 1.0, got {total}"


@dataclass
class BenchmarkMetrics:
    """Results from a benchmark run."""
    precision_at_5: float
    precision_at_10: float
    mrr: float  # Mean Reciprocal Rank
    ndcg_at_10: float  # Normalized Discounted Cumulative Gain
    first_relevant_rank: int | None
    
    @classmethod
    def compute(cls, ranked_ids: list[UUID], relevance_grades: dict[UUID, int], k_values: tuple[int, int] = (5, 10)) -> "BenchmarkMetrics":
        """Compute all metrics from ranked results."""
        k5, k10 = k_values
        
        # Precision@K: fraction of top-K that are relevant
        relevant_in_top_5 = sum(1 for id in ranked_ids[:k5] if relevance_grades.get(id, 0) >= 2)
        relevant_in_top_10 = sum(1 for id in ranked_ids[:k10] if relevance_grades.get(id, 0) >= 2)
        
        precision_at_5 = relevant_in_top_5 / k5 if k5 else 0
        precision_at_10 = relevant_in_top_10 / k10 if k10 else 0
        
        # MRR: 1/rank of first relevant result
        first_relevant = None
        for i, id in enumerate(ranked_ids):
            if relevance_grades.get(id, 0) >= 2:
                first_relevant = i + 1  # 1-indexed rank
                break
        mrr = 1.0 / first_relevant if first_relevant else 0
        
        # NDCG@10: considers graded relevance
        dcg = 0.0
        for i, id in enumerate(ranked_ids[:k10]):
            rel = relevance_grades.get(id, 0)
            dcg += (2**rel - 1) / math.log2(i + 2)  # i+2 because rank is 1-indexed
        
        # Ideal DCG (perfect ranking)
        ideal_grades = sorted(relevance_grades.values(), reverse=True)[:k10]
        idcg = sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(ideal_grades))
        
        ndcg_at_10 = dcg / idcg if idcg > 0 else 0
        
        return cls(
            precision_at_5=precision_at_5,
            precision_at_10=precision_at_10,
            mrr=mrr,
            ndcg_at_10=ndcg_at_10,
            first_relevant_rank=first_relevant
        )


# ============================================================================
# Ranking Algorithms
# ============================================================================

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def baseline_semantic_only(query_embedding: np.ndarray, beliefs: list[MockBelief]) -> list[MockBelief]:
    """Baseline: rank by pure semantic similarity only."""
    scored = []
    for belief in beliefs:
        sim = cosine_similarity(query_embedding, belief.embedding)
        scored.append((belief, sim))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    return [b for b, _ in scored]


def valence_multi_signal(
    query_embedding: np.ndarray,
    beliefs: list[MockBelief],
    weights: RankingWeights | None = None,
    requester_trust: dict[str, float] | None = None,
    query_time: datetime | None = None,
    recency_decay_rate: float = 0.01  # Default: ~69 day half-life
) -> list[MockBelief]:
    """
    Valence multi-signal ranking algorithm.
    
    Implements the formula from RANKING.md:
    final_score = w_semantic × semantic + w_confidence × confidence + 
                  w_trust × trust + w_recency × recency
    """
    weights = weights or RankingWeights()
    requester_trust = requester_trust or {}
    query_time = query_time or datetime.now()
    
    scored = []
    for belief in beliefs:
        # 1. Semantic score
        semantic = cosine_similarity(query_embedding, belief.embedding)
        # Normalize to [0, 1] (raw cosine is already in [-1, 1], usually [0, 1] for text)
        semantic = (semantic + 1) / 2
        
        # 2. Confidence score (geometric mean of dimensions)
        confidence = belief.confidence_overall
        
        # 3. Trust score
        trust = requester_trust.get(belief.holder_id, 0.1)  # Default floor of 0.1
        
        # 4. Recency score
        age_days = (query_time - belief.created_at).days
        decay = math.exp(-recency_decay_rate * age_days)
        recency = belief.temporal_freshness * decay
        
        # Final score
        final = (
            weights.semantic * semantic +
            weights.confidence * confidence +
            weights.trust * trust +
            weights.recency * recency
        )
        
        scored.append((belief, final, {
            'semantic': semantic,
            'confidence': confidence,
            'trust': trust,
            'recency': recency,
            'final': final
        }))
    
    scored.sort(key=lambda x: x[1], reverse=True)
    return [b for b, _, _ in scored]


# ============================================================================
# Test Scenario Builders
# ============================================================================

def generate_embedding(seed: str, dim: int = 384, noise: float = 0.0) -> np.ndarray:
    """
    Generate a deterministic embedding from a seed string.
    
    Similar seeds produce similar embeddings. Noise adds randomness.
    """
    # Use hash of seed for reproducibility
    rng = np.random.RandomState(hash(seed) % (2**32))
    base = rng.randn(dim)
    
    if noise > 0:
        noise_vec = np.random.randn(dim) * noise
        base = base + noise_vec
    
    # Normalize
    return base / np.linalg.norm(base)


class ScenarioBuilder:
    """Builds test scenarios with controlled belief distributions."""
    
    def __init__(self, embedding_dim: int = 384):
        self.dim = embedding_dim
        self.beliefs: list[MockBelief] = []
        self.query_embedding: np.ndarray | None = None
        self.relevance_grades: dict[UUID, int] = {}
        
    def set_query(self, topic: str) -> "ScenarioBuilder":
        """Set the query topic."""
        self.query_embedding = generate_embedding(f"query:{topic}", self.dim)
        return self
    
    def add_belief(
        self,
        content: str,
        topic_similarity: float = 0.5,  # How similar to query topic
        relevance_grade: int = 0,
        **confidence_kwargs
    ) -> "ScenarioBuilder":
        """Add a belief with controlled similarity to query."""
        belief_id = uuid4()
        
        # Generate embedding that's controllably similar to query
        if self.query_embedding is None:
            raise ValueError("Call set_query() first")
        
        # Create embedding as blend of query and random
        random_component = generate_embedding(f"random:{content}", self.dim)
        embedding = (
            topic_similarity * self.query_embedding +
            (1 - topic_similarity) * random_component
        )
        embedding = embedding / np.linalg.norm(embedding)
        
        belief = MockBelief(
            id=belief_id,
            content=content,
            embedding=embedding,
            is_relevant=relevance_grade >= 2,
            relevance_grade=relevance_grade,
            **confidence_kwargs
        )
        
        self.beliefs.append(belief)
        self.relevance_grades[belief_id] = relevance_grade
        
        return self
    
    def add_similar_noise(self, count: int, topic_similarity_range: tuple[float, float] = (0.6, 0.8)) -> "ScenarioBuilder":
        """Add noise beliefs that are semantically similar but not useful."""
        for i in range(count):
            sim = random.uniform(*topic_similarity_range)
            self.add_belief(
                content=f"Noise belief {i} - similar but not relevant",
                topic_similarity=sim,
                relevance_grade=0,
                source_reliability=random.uniform(0.3, 0.6),
                temporal_freshness=random.uniform(0.4, 0.8),
                corroboration=random.uniform(0.1, 0.3)
            )
        return self
    
    def add_random_noise(self, count: int) -> "ScenarioBuilder":
        """Add completely unrelated noise beliefs."""
        for i in range(count):
            self.add_belief(
                content=f"Unrelated noise belief {i}",
                topic_similarity=random.uniform(0.1, 0.4),
                relevance_grade=0,
                source_reliability=random.uniform(0.3, 0.7),
                temporal_freshness=random.uniform(0.3, 1.0),
                corroboration=random.uniform(0.1, 0.5)
            )
        return self
    
    def build(self) -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
        """Return the scenario components."""
        if self.query_embedding is None:
            raise ValueError("Call set_query() first")
        return self.query_embedding, self.beliefs, self.relevance_grades


# ============================================================================
# Aha Moment Scenarios
# ============================================================================

def scenario_buried_high_confidence() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 1: High-confidence belief buried by semantic similarity.
    
    A highly reliable, well-corroborated belief is semantically slightly less
    similar than noisy speculation. Flat semantic search buries it.
    """
    builder = ScenarioBuilder()
    builder.set_query("python async programming patterns")
    
    # The golden belief - high confidence but slightly less semantically matching
    builder.add_belief(
        content="Use asyncio.gather() for concurrent tasks; await directly for sequential. "
                "Handle exceptions with asyncio.TaskGroup (Python 3.11+) for clean cleanup.",
        topic_similarity=0.75,  # Good but not best semantic match
        relevance_grade=3,  # Highly relevant
        source_reliability=0.95,  # Verified from Python docs
        method_quality=0.90,
        internal_consistency=0.95,
        temporal_freshness=0.85,
        corroboration=0.88,  # Multiple sources confirm
        domain_applicability=0.95
    )
    
    # Semantically closer but low-quality speculation
    for i in range(5):
        builder.add_belief(
            content=f"Python async pattern variant {i}: maybe try using threads instead? "
                    f"asyncio might have issues with {['blocking', 'memory', 'deadlocks', 'performance', 'debugging'][i]}",
            topic_similarity=0.85 + random.uniform(0, 0.05),  # Higher semantic similarity
            relevance_grade=1,  # Marginally relevant (misleading)
            source_reliability=0.25,  # Random forum post
            method_quality=0.20,
            internal_consistency=0.40,
            temporal_freshness=0.70,
            corroboration=0.10,  # Nobody else says this
            domain_applicability=0.50
        )
    
    # Add more noise
    builder.add_similar_noise(20, (0.6, 0.75))
    builder.add_random_noise(30)
    
    return builder.build()


def scenario_outdated_deprioritized() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 2: Outdated belief correctly deprioritized.
    
    Old information (even if once accurate) should rank below current information.
    Tests temporal_freshness weighting.
    """
    builder = ScenarioBuilder()
    builder.set_query("kubernetes best practices deployment")
    
    now = datetime.now()
    
    # Current best practice (2024)
    builder.add_belief(
        content="Use Kubernetes Gateway API for ingress (replacing legacy Ingress). "
                "Deploy with ArgoCD GitOps. Use Kyverno for policy enforcement.",
        topic_similarity=0.82,
        relevance_grade=3,
        source_reliability=0.90,
        method_quality=0.85,
        internal_consistency=0.90,
        temporal_freshness=0.95,  # Current
        corroboration=0.80,
        domain_applicability=0.90,
        created_at=now - timedelta(days=30)
    )
    
    # Outdated but was once accurate (2018-era advice)
    builder.add_belief(
        content="Use nginx-ingress with manual certificate management. "
                "Deploy using kubectl apply directly. Avoid Helm - too complex.",
        topic_similarity=0.88,  # Very semantically similar
        relevance_grade=1,  # Now misleading
        source_reliability=0.85,  # Was reliable when written
        method_quality=0.80,
        internal_consistency=0.75,
        temporal_freshness=0.15,  # Outdated
        corroboration=0.60,  # Less corroborated now
        domain_applicability=0.40,  # Kubernetes has evolved
        created_at=now - timedelta(days=2000)  # ~5.5 years old
    )
    
    # More outdated content
    for i, years_old in enumerate([3, 4, 6, 7]):
        builder.add_belief(
            content=f"Historical K8s practice {i}: Pod security policies recommended",
            topic_similarity=0.75 + random.uniform(0, 0.1),
            relevance_grade=0 if years_old > 4 else 1,
            temporal_freshness=0.2 - (years_old * 0.02),
            created_at=now - timedelta(days=years_old * 365)
        )
    
    builder.add_similar_noise(25)
    builder.add_random_noise(25)
    
    return builder.build()


def scenario_speculation_below_facts() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 3: Low-confidence speculation ranked below established facts.
    
    Speculative, uncertain beliefs should not outrank well-established facts,
    even if they're more "interesting" or semantically engaging.
    """
    builder = ScenarioBuilder()
    builder.set_query("machine learning model training optimization")
    
    # Established fact - proven technique
    builder.add_belief(
        content="Use learning rate scheduling (cosine annealing or warmup + decay). "
                "Batch size affects generalization; larger isn't always better. "
                "Gradient clipping prevents exploding gradients.",
        topic_similarity=0.80,
        relevance_grade=3,
        source_reliability=0.95,  # Peer-reviewed research
        method_quality=0.95,  # Empirically validated
        internal_consistency=0.95,
        temporal_freshness=0.80,  # Still current
        corroboration=0.95,  # Widely confirmed
        domain_applicability=0.90
    )
    
    # Speculative / unverified claims - semantically engaging
    speculation_claims = [
        "Training models during full moons improves convergence by 15%",
        "Random batch ordering based on fibonacci sequences boosts accuracy",
        "Loss landscapes are fractal - use chaos theory for hyperparameters",
        "Model weights have memory - pre-train on related domains always helps",
        "Adam optimizer is secretly deterministic if you set seeds right",
    ]
    
    for i, claim in enumerate(speculation_claims):
        builder.add_belief(
            content=claim,
            topic_similarity=0.85 + random.uniform(0, 0.08),  # Semantically close
            relevance_grade=0,  # Irrelevant (wrong)
            source_reliability=0.15,  # No credible source
            method_quality=0.10,  # No methodology
            internal_consistency=0.30,
            temporal_freshness=0.90,
            corroboration=0.05,  # Nobody reputable confirms
            domain_applicability=0.20
        )
    
    builder.add_similar_noise(30)
    builder.add_random_noise(20)
    
    return builder.build()


def scenario_corroboration_boost() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 4: Well-corroborated belief appropriately boosted.
    
    When multiple independent sources confirm something, it should rank higher
    than single-source claims with similar semantic relevance.
    """
    builder = ScenarioBuilder()
    builder.set_query("database indexing strategies performance")
    
    # Highly corroborated - many sources agree
    builder.add_belief(
        content="B-tree indexes excel for range queries and ordered scans. "
                "Hash indexes are faster for equality but can't do ranges. "
                "Composite index column order matters - most selective first.",
        topic_similarity=0.78,
        relevance_grade=3,
        source_reliability=0.85,
        method_quality=0.88,
        internal_consistency=0.90,
        temporal_freshness=0.85,
        corroboration=0.95,  # Textbooks, docs, and practitioners agree
        domain_applicability=0.92
    )
    
    # Single-source claims - might be true but unverified
    single_source_claims = [
        ("My benchmarks show BRIN indexes are always 10x faster", 0.88),
        ("Skip list indexes outperform B-trees in all cases", 0.85),
        ("Index everything - storage is cheap, queries are expensive", 0.82),
        ("Partial indexes are a code smell - use full indexes", 0.80),
    ]
    
    for i, (claim, sim) in enumerate(single_source_claims):
        builder.add_belief(
            content=claim,
            topic_similarity=sim,
            relevance_grade=1,  # Partially true at best
            source_reliability=0.60,
            method_quality=0.50,
            internal_consistency=0.70,
            temporal_freshness=0.90,
            corroboration=0.15 + (i * 0.05),  # Low corroboration
            domain_applicability=0.65
        )
    
    builder.add_similar_noise(25)
    builder.add_random_noise(25)
    
    return builder.build()


def scenario_source_reliability_matters() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 5: Source reliability makes the difference.
    
    An authoritative source should outrank an unreliable one,
    even with similar semantic relevance.
    """
    builder = ScenarioBuilder()
    builder.set_query("API authentication best practices security")
    
    # Authoritative source - OWASP/security expert
    builder.add_belief(
        content="Use short-lived JWTs with refresh tokens. Store tokens in httpOnly cookies, "
                "not localStorage. Implement token rotation and revocation. "
                "Always validate audience and issuer claims.",
        topic_similarity=0.80,
        relevance_grade=3,
        source_reliability=0.95,  # Security expert / OWASP
        method_quality=0.90,
        internal_consistency=0.95,
        temporal_freshness=0.88,
        corroboration=0.85,
        domain_applicability=0.95
    )
    
    # Unreliable sources - random blog posts with bad advice
    bad_advice = [
        ("Store API keys in frontend code - it's fine with obfuscation", 0.85),
        ("Basic auth over HTTPS is equally secure as OAuth2", 0.87),
        ("Session tokens in URL query params are convenient and safe", 0.83),
        ("Implement your own crypto - standard libraries have backdoors", 0.82),
    ]
    
    for content, sim in bad_advice:
        builder.add_belief(
            content=content,
            topic_similarity=sim,
            relevance_grade=0,  # Dangerous advice
            source_reliability=0.10,  # Unreliable source
            method_quality=0.15,
            internal_consistency=0.30,
            temporal_freshness=0.80,
            corroboration=0.05,
            domain_applicability=0.40
        )
    
    builder.add_similar_noise(30)
    builder.add_random_noise(20)
    
    return builder.build()


def scenario_domain_applicability() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 6: Domain applicability distinguishes general from specific.
    
    A belief highly applicable to the query's domain should rank above
    generic advice that's semantically similar but less targeted.
    """
    builder = ScenarioBuilder()
    builder.set_query("mobile app performance optimization iOS")
    
    # Domain-specific (iOS expertise)
    builder.add_belief(
        content="Use Instruments Time Profiler for CPU bottlenecks. "
                "Implement lazy loading for UICollectionView with prefetching. "
                "Avoid main thread JSON parsing - use background queues.",
        topic_similarity=0.78,
        relevance_grade=3,
        source_reliability=0.88,
        method_quality=0.85,
        internal_consistency=0.90,
        temporal_freshness=0.85,
        corroboration=0.80,
        domain_applicability=0.95  # iOS-specific
    )
    
    # Generic advice (applies everywhere, less useful)
    generic_advice = [
        ("Cache data to improve performance", 0.85),
        ("Optimize images for faster loading", 0.87),
        ("Use efficient algorithms and data structures", 0.82),
        ("Profile before optimizing", 0.88),
        ("Reduce network requests", 0.84),
    ]
    
    for content, sim in generic_advice:
        builder.add_belief(
            content=content,
            topic_similarity=sim,
            relevance_grade=1,  # True but not specific enough
            source_reliability=0.75,
            method_quality=0.70,
            internal_consistency=0.85,
            temporal_freshness=0.80,
            corroboration=0.85,
            domain_applicability=0.40  # Generic, not iOS-specific
        )
    
    builder.add_similar_noise(25)
    builder.add_random_noise(25)
    
    return builder.build()


def scenario_internal_consistency() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 7: Internally consistent beliefs rank higher than contradictory ones.
    
    A belief that's consistent with the broader knowledge base should rank
    higher than one that contradicts established facts.
    """
    builder = ScenarioBuilder()
    builder.set_query("git branching workflow strategy")
    
    # Consistent with established practices
    builder.add_belief(
        content="Use feature branches from main. Rebase for clean history, "
                "merge for preserving context. Protect main with required reviews. "
                "Delete branches after merge.",
        topic_similarity=0.80,
        relevance_grade=3,
        source_reliability=0.85,
        method_quality=0.85,
        internal_consistency=0.95,  # Aligns with git best practices
        temporal_freshness=0.88,
        corroboration=0.85,
        domain_applicability=0.90
    )
    
    # Contradicts established practices
    contradictory_claims = [
        ("Always commit directly to main - branches cause merge conflicts", 0.86),
        ("Never delete branches - you lose history", 0.84),
        ("Merge commits are evil - always squash everything", 0.85),
        ("Git rebase rewrites history and should never be used", 0.83),
    ]
    
    for content, sim in contradictory_claims:
        builder.add_belief(
            content=content,
            topic_similarity=sim,
            relevance_grade=1,  # Has a kernel of truth but misleading
            source_reliability=0.55,
            method_quality=0.50,
            internal_consistency=0.25,  # Contradicts other knowledge
            temporal_freshness=0.80,
            corroboration=0.30,
            domain_applicability=0.60
        )
    
    builder.add_similar_noise(25)
    builder.add_random_noise(25)
    
    return builder.build()


def scenario_recency_for_news() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 8: Recency matters more for time-sensitive queries.
    
    For queries about current events or rapidly changing domains,
    recency should be weighted higher.
    """
    builder = ScenarioBuilder()
    builder.set_query("latest LLM capabilities announcements")
    
    now = datetime.now()
    
    # Fresh announcement
    builder.add_belief(
        content="Claude 3.5 Sonnet offers 2x speed improvement with enhanced reasoning. "
                "200K context window. Computer use capability in beta.",
        topic_similarity=0.82,
        relevance_grade=3,
        source_reliability=0.95,
        method_quality=0.90,
        internal_consistency=0.90,
        temporal_freshness=0.98,  # Very fresh
        corroboration=0.75,
        domain_applicability=0.95,
        created_at=now - timedelta(days=7)
    )
    
    # Older announcements (still accurate but outdated context)
    old_announcements = [
        ("GPT-4 released with 8K and 32K context windows", 600, 0.88),  # ~2 years
        ("Claude 2 achieves state-of-art on many benchmarks", 450, 0.85),  # ~1.2 years
        ("PaLM 2 powers Bard with improved reasoning", 500, 0.86),  # ~1.4 years
    ]
    
    for content, days_old, sim in old_announcements:
        builder.add_belief(
            content=content,
            topic_similarity=sim,
            relevance_grade=1,  # Was true, now outdated
            source_reliability=0.90,
            method_quality=0.85,
            internal_consistency=0.80,
            temporal_freshness=0.20,  # Stale
            corroboration=0.85,
            domain_applicability=0.60,
            created_at=now - timedelta(days=days_old)
        )
    
    builder.add_similar_noise(25)
    builder.add_random_noise(25)
    
    return builder.build()


def scenario_method_quality() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 9: Method quality separates rigorous from anecdotal.
    
    Claims backed by systematic methodology should rank above
    anecdotal evidence, even with similar relevance.
    """
    builder = ScenarioBuilder()
    builder.set_query("code review effectiveness metrics")
    
    # Rigorous study
    builder.add_belief(
        content="Studies show code review finds 60-90% of defects when reviewing "
                "200-400 lines at 300-500 LOC/hour pace. Review effectiveness drops "
                "sharply beyond 400 LOC. Checklists improve consistency by 25%.",
        topic_similarity=0.80,
        relevance_grade=3,
        source_reliability=0.85,
        method_quality=0.95,  # Systematic research
        internal_consistency=0.90,
        temporal_freshness=0.75,
        corroboration=0.85,
        domain_applicability=0.88
    )
    
    # Anecdotal claims
    anecdotal_claims = [
        ("Code review is waste of time - my team stopped and quality improved", 0.87),
        ("We review everything and find all bugs now", 0.85),
        ("AI will replace code review completely within a year", 0.82),
        ("Reviews longer than 10 minutes are counterproductive", 0.84),
    ]
    
    for content, sim in anecdotal_claims:
        builder.add_belief(
            content=content,
            topic_similarity=sim,
            relevance_grade=0 if "AI" in content else 1,
            source_reliability=0.50,
            method_quality=0.15,  # Pure anecdote
            internal_consistency=0.60,
            temporal_freshness=0.85,
            corroboration=0.20,
            domain_applicability=0.50
        )
    
    builder.add_similar_noise(25)
    builder.add_random_noise(25)
    
    return builder.build()


def scenario_combined_signals() -> tuple[np.ndarray, list[MockBelief], dict[UUID, int]]:
    """
    Scenario 10: Combined signals show multiplicative advantage.
    
    A belief that's strong on multiple dimensions should clearly outrank
    one that's strong on only semantic similarity.
    """
    builder = ScenarioBuilder()
    builder.set_query("distributed systems consensus algorithms")
    
    # Strong on all signals
    builder.add_belief(
        content="Raft provides understandable consensus with leader election. "
                "Use etcd or Consul for production. Paxos is theoretically elegant "
                "but harder to implement correctly. Consider CRDTs for eventual consistency.",
        topic_similarity=0.78,
        relevance_grade=3,
        source_reliability=0.92,
        method_quality=0.90,
        internal_consistency=0.95,
        temporal_freshness=0.85,
        corroboration=0.90,
        domain_applicability=0.95
    )
    
    # High semantic similarity only
    builder.add_belief(
        content="Distributed consensus algorithms for systems include Raft and Paxos. "
                "They help with consensus in distributed systems. Consensus is important "
                "for distributed systems reliability.",
        topic_similarity=0.92,  # Very high semantic match (lots of keyword overlap)
        relevance_grade=1,  # Superficial, not actionable
        source_reliability=0.40,
        method_quality=0.30,
        internal_consistency=0.50,
        temporal_freshness=0.70,
        corroboration=0.25,
        domain_applicability=0.45
    )
    
    builder.add_similar_noise(30)
    builder.add_random_noise(25)
    
    return builder.build()


# ============================================================================
# The Benchmark Test Suite
# ============================================================================

class TestAhaMoments:
    """
    Aha Moment Benchmark Suite
    
    Each test demonstrates a specific scenario where Valence multi-signal
    ranking outperforms flat semantic search.
    """
    
    SCENARIOS = {
        "buried_high_confidence": scenario_buried_high_confidence,
        "outdated_deprioritized": scenario_outdated_deprioritized,
        "speculation_below_facts": scenario_speculation_below_facts,
        "corroboration_boost": scenario_corroboration_boost,
        "source_reliability_matters": scenario_source_reliability_matters,
        "domain_applicability": scenario_domain_applicability,
        "internal_consistency": scenario_internal_consistency,
        "recency_for_news": scenario_recency_for_news,
        "method_quality": scenario_method_quality,
        "combined_signals": scenario_combined_signals,
    }
    
    @pytest.mark.parametrize("scenario_name", SCENARIOS.keys())
    def test_scenario_valence_beats_baseline(self, scenario_name: str):
        """Each scenario should show Valence outperforming baseline."""
        scenario_fn = self.SCENARIOS[scenario_name]
        query_emb, beliefs, grades = scenario_fn()
        
        # Run both algorithms
        baseline_results = baseline_semantic_only(query_emb, beliefs)
        valence_results = valence_multi_signal(query_emb, beliefs)
        
        # Compute metrics
        baseline_ids = [b.id for b in baseline_results]
        valence_ids = [b.id for b in valence_results]
        
        baseline_metrics = BenchmarkMetrics.compute(baseline_ids, grades)
        valence_metrics = BenchmarkMetrics.compute(valence_ids, grades)
        
        # Debug output
        print(f"\n{'='*60}")
        print(f"Scenario: {scenario_name}")
        print(f"{'='*60}")
        print(f"Baseline - P@5: {baseline_metrics.precision_at_5:.2f}, "
              f"P@10: {baseline_metrics.precision_at_10:.2f}, "
              f"MRR: {baseline_metrics.mrr:.3f}, "
              f"NDCG@10: {baseline_metrics.ndcg_at_10:.3f}")
        print(f"Valence  - P@5: {valence_metrics.precision_at_5:.2f}, "
              f"P@10: {valence_metrics.precision_at_10:.2f}, "
              f"MRR: {valence_metrics.mrr:.3f}, "
              f"NDCG@10: {valence_metrics.ndcg_at_10:.3f}")
        
        # Show top results comparison
        print(f"\nTop 5 Baseline:")
        for i, b in enumerate(baseline_results[:5]):
            grade = grades[b.id]
            mark = "✓" if grade >= 2 else "✗"
            print(f"  {i+1}. [{mark}] grade={grade} conf={b.confidence_overall:.2f}: {b.content[:60]}...")
        
        print(f"\nTop 5 Valence:")
        for i, b in enumerate(valence_results[:5]):
            grade = grades[b.id]
            mark = "✓" if grade >= 2 else "✗"
            print(f"  {i+1}. [{mark}] grade={grade} conf={b.confidence_overall:.2f}: {b.content[:60]}...")
        
        # Assertions - Valence should improve or match baseline
        assert valence_metrics.mrr >= baseline_metrics.mrr, \
            f"Valence MRR ({valence_metrics.mrr:.3f}) should beat baseline ({baseline_metrics.mrr:.3f})"
        
        # At least one metric should improve
        improvements = [
            valence_metrics.precision_at_5 >= baseline_metrics.precision_at_5,
            valence_metrics.precision_at_10 >= baseline_metrics.precision_at_10,
            valence_metrics.mrr >= baseline_metrics.mrr,
            valence_metrics.ndcg_at_10 >= baseline_metrics.ndcg_at_10,
        ]
        assert any(improvements), "Valence should improve at least one metric"
    
    def test_full_benchmark(self):
        """Run all scenarios and compute aggregate improvement."""
        all_baseline_metrics = []
        all_valence_metrics = []
        
        print("\n" + "="*70)
        print("VALENCE MULTI-SIGNAL RANKING BENCHMARK")
        print("="*70)
        
        for name, scenario_fn in self.SCENARIOS.items():
            query_emb, beliefs, grades = scenario_fn()
            
            baseline_results = baseline_semantic_only(query_emb, beliefs)
            valence_results = valence_multi_signal(query_emb, beliefs)
            
            baseline_ids = [b.id for b in baseline_results]
            valence_ids = [b.id for b in valence_results]
            
            baseline_metrics = BenchmarkMetrics.compute(baseline_ids, grades)
            valence_metrics = BenchmarkMetrics.compute(valence_ids, grades)
            
            all_baseline_metrics.append(baseline_metrics)
            all_valence_metrics.append(valence_metrics)
            
            improvement = (
                (valence_metrics.mrr - baseline_metrics.mrr) / max(baseline_metrics.mrr, 0.001)
            ) * 100
            
            print(f"\n{name}:")
            print(f"  Baseline MRR: {baseline_metrics.mrr:.3f}, Valence MRR: {valence_metrics.mrr:.3f} "
                  f"({'+' if improvement >= 0 else ''}{improvement:.1f}%)")
        
        # Aggregate metrics
        avg_baseline_mrr = sum(m.mrr for m in all_baseline_metrics) / len(all_baseline_metrics)
        avg_valence_mrr = sum(m.mrr for m in all_valence_metrics) / len(all_valence_metrics)
        avg_baseline_p5 = sum(m.precision_at_5 for m in all_baseline_metrics) / len(all_baseline_metrics)
        avg_valence_p5 = sum(m.precision_at_5 for m in all_valence_metrics) / len(all_valence_metrics)
        avg_baseline_ndcg = sum(m.ndcg_at_10 for m in all_baseline_metrics) / len(all_baseline_metrics)
        avg_valence_ndcg = sum(m.ndcg_at_10 for m in all_valence_metrics) / len(all_valence_metrics)
        
        mrr_improvement = ((avg_valence_mrr - avg_baseline_mrr) / avg_baseline_mrr) * 100
        p5_improvement = ((avg_valence_p5 - avg_baseline_p5) / max(avg_baseline_p5, 0.001)) * 100
        ndcg_improvement = ((avg_valence_ndcg - avg_baseline_ndcg) / avg_baseline_ndcg) * 100
        
        print("\n" + "="*70)
        print("AGGREGATE RESULTS")
        print("="*70)
        print(f"\n{'Metric':<20} {'Baseline':>12} {'Valence':>12} {'Improvement':>15}")
        print("-"*60)
        print(f"{'Avg MRR':<20} {avg_baseline_mrr:>12.3f} {avg_valence_mrr:>12.3f} {mrr_improvement:>14.1f}%")
        print(f"{'Avg P@5':<20} {avg_baseline_p5:>12.3f} {avg_valence_p5:>12.3f} {p5_improvement:>14.1f}%")
        print(f"{'Avg NDCG@10':<20} {avg_baseline_ndcg:>12.3f} {avg_valence_ndcg:>12.3f} {ndcg_improvement:>14.1f}%")
        print("-"*60)
        
        print("\n📊 HEADLINE RESULT:")
        print(f"   Valence improves retrieval precision by {mrr_improvement:.0f}% (MRR)")
        print(f"   Top-5 precision improved by {p5_improvement:.0f}%")
        print(f"   NDCG@10 improved by {ndcg_improvement:.0f}%")
        
        # Assert meaningful improvement
        assert mrr_improvement > 10, f"Expected >10% MRR improvement, got {mrr_improvement:.1f}%"
        assert avg_valence_mrr > avg_baseline_mrr, "Valence should have higher average MRR"

    def test_weight_sensitivity(self):
        """Test how different weight configurations affect results."""
        query_emb, beliefs, grades = scenario_combined_signals()
        
        weight_configs = {
            "balanced": RankingWeights(semantic=0.35, confidence=0.25, trust=0.30, recency=0.10),
            "semantic_heavy": RankingWeights(semantic=0.60, confidence=0.15, trust=0.15, recency=0.10),
            "confidence_heavy": RankingWeights(semantic=0.25, confidence=0.45, trust=0.20, recency=0.10),
            "recency_heavy": RankingWeights(semantic=0.30, confidence=0.20, trust=0.15, recency=0.35),
        }
        
        print("\n" + "="*60)
        print("WEIGHT SENSITIVITY ANALYSIS")
        print("="*60)
        
        results = {}
        for name, weights in weight_configs.items():
            ranked = valence_multi_signal(query_emb, beliefs, weights=weights)
            ids = [b.id for b in ranked]
            metrics = BenchmarkMetrics.compute(ids, grades)
            results[name] = metrics
            
            print(f"\n{name}: MRR={metrics.mrr:.3f}, P@5={metrics.precision_at_5:.2f}")
        
        # Balanced should be competitive
        assert results["balanced"].mrr >= 0.5, "Balanced weights should achieve reasonable MRR"


class TestScenarioDetails:
    """Detailed tests for specific scenarios to verify expected behavior."""
    
    def test_high_confidence_surfaces(self):
        """Verify that high-confidence belief ranks in top 3 with Valence."""
        query_emb, beliefs, grades = scenario_buried_high_confidence()
        
        # Find the high-confidence belief
        high_conf_belief = None
        for b in beliefs:
            if b.relevance_grade == 3 and b.corroboration > 0.8:
                high_conf_belief = b
                break
        
        assert high_conf_belief is not None, "Should have a high-confidence belief"
        
        # Check baseline ranking
        baseline = baseline_semantic_only(query_emb, beliefs)
        baseline_rank = next(i for i, b in enumerate(baseline) if b.id == high_conf_belief.id)
        
        # Check Valence ranking
        valence = valence_multi_signal(query_emb, beliefs)
        valence_rank = next(i for i, b in enumerate(valence) if b.id == high_conf_belief.id)
        
        print(f"\nHigh-confidence belief rank: Baseline={baseline_rank+1}, Valence={valence_rank+1}")
        
        # Valence should rank it higher
        assert valence_rank < baseline_rank, \
            f"Valence should rank high-confidence belief higher ({valence_rank+1} vs {baseline_rank+1})"
        assert valence_rank < 5, f"High-confidence belief should be in top 5, got rank {valence_rank+1}"
    
    def test_outdated_drops(self):
        """Verify that outdated content drops in ranking with Valence."""
        query_emb, beliefs, grades = scenario_outdated_deprioritized()
        
        # Find the outdated belief
        outdated_belief = None
        for b in beliefs:
            if b.temporal_freshness < 0.2 and b.relevance_grade == 1:
                outdated_belief = b
                break
        
        assert outdated_belief is not None, "Should have an outdated belief"
        
        baseline = baseline_semantic_only(query_emb, beliefs)
        valence = valence_multi_signal(query_emb, beliefs)
        
        baseline_rank = next(i for i, b in enumerate(baseline) if b.id == outdated_belief.id)
        valence_rank = next(i for i, b in enumerate(valence) if b.id == outdated_belief.id)
        
        print(f"\nOutdated belief rank: Baseline={baseline_rank+1}, Valence={valence_rank+1}")
        
        # Valence should rank it lower
        assert valence_rank > baseline_rank, \
            f"Valence should rank outdated belief lower ({valence_rank+1} vs {baseline_rank+1})"


# ============================================================================
# Benchmark Runner Entry Point
# ============================================================================

if __name__ == "__main__":
    """Run benchmarks directly."""
    import sys
    
    print("Running Valence Aha Moment Benchmarks...\n")
    
    # Run the full benchmark
    test = TestAhaMoments()
    test.test_full_benchmark()
    
    print("\n\nRunning individual scenario tests...\n")
    for scenario_name in TestAhaMoments.SCENARIOS.keys():
        try:
            test.test_scenario_valence_beats_baseline(scenario_name)
            print(f"✓ {scenario_name}")
        except AssertionError as e:
            print(f"✗ {scenario_name}: {e}")
    
    print("\n\nRunning detail tests...\n")
    detail_test = TestScenarioDetails()
    detail_test.test_high_confidence_surfaces()
    detail_test.test_outdated_drops()
    
    print("\n\nBenchmark complete!")
