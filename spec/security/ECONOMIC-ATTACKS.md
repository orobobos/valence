# Economic Attack Defenses — Security Specification

*"Any incentive system can be gamed. The goal isn't perfection—it's making attacks more expensive than honest participation."*

---

## Overview

This document catalogs known economic attack vectors against Valence's reputation-based incentive system and specifies defense mechanisms. The core principle: **attacks must cost more than they gain**, creating negative expected value for adversaries.

### Defense Philosophy

1. **Defense in depth** — Multiple independent detection layers
2. **Economic deterrence** — Make attacks unprofitable, not just detectable
3. **Graceful degradation** — Attacks should reduce attacker's capability, not crash the network
4. **Retroactive justice** — Even successful attacks face clawback
5. **Transparency** — Detection mechanisms are public; security through economics, not obscurity

---

## 1. Attack Taxonomy

### 1.1 Reputation Farming

**Attack:** Build reputation through low-effort, low-risk contributions, then exploit accumulated trust.

**Mechanism:**
- Submit many trivial confirmations of obvious beliefs
- Target low-confidence beliefs (low stake requirement)
- Avoid controversial or risky verifications
- Once reputation is high, make one large fraudulent claim or sell account

**Variants:**
- **Slow farm**: Years of minor contributions, one big exploitation
- **Parallel farm**: Multiple identities farmed simultaneously
- **Bootstrapped farm**: Create easy-to-verify beliefs, self-confirm with Sybil accounts

**Impact:** Corrupts reputation signal; high-rep entities may be gamers not experts.

---

### 1.2 Reputation Laundering

**Attack:** Transfer ill-gotten reputation to a clean identity to escape penalties or detection history.

**Mechanism:**
- Build reputation (legitimately or via farming)
- Engage in detectable bad behavior
- Before penalties hit, "transfer" reputation via:
  - Coordinated mutual verifications with clean identity
  - Bounty system abuse (clean identity "earns" bounties from dirty identity)
  - Creating beliefs that only clean identity can verify

**Variants:**
- **Serial restart**: Abandon penalized identity, start fresh
- **Reputation mule**: Third party holds reputation, rents it back
- **Federated escape**: Move to different federation before penalties propagate

**Impact:** Penalties become meaningless if reputation is easily movable.

---

### 1.3 Pump and Dump

**Attack:** Build substantial reputation, make one massive false claim (benefiting external interests), disappear.

**Mechanism:**
- Establish genuine expertise over months/years
- Accumulate high reputation through legitimate contributions
- At strategic moment, publish high-confidence false belief affecting external markets/decisions
- Accept reputation loss (planned exit)
- Profit from external position (shorts, competing products, political outcomes)

**Variants:**
- **Market pump**: False belief inflates asset prices, attacker sells
- **Competitive sabotage**: False belief damages competitor's product/reputation
- **Political manipulation**: False belief influences elections/policy
- **Coordinated dump**: Multiple high-rep accounts pump simultaneously

**Impact:** External value extraction; most dangerous attack vector.

---

### 1.4 Collusion Rings

**Attack:** Group of agents mutually boost each other's reputation without providing genuine value.

**Mechanism:**
- Form closed group (2-100 agents)
- Create believable-but-unverifiable claims
- Group members confirm each other's claims
- Avoid verifying outside the ring (reduces detection)
- Collectively reach high reputation, extract value

**Variants:**
- **Tight ring**: Small group (2-5), high mutual verification rate
- **Loose ring**: Larger group (20+), statistical boosting harder to detect
- **Hierarchical ring**: Leader coordinates, members don't know each other
- **Cross-federation ring**: Members in different federations to evade detection

**Impact:** Inflates reputation of untrustworthy agents; dilutes value of reputation signal.

---

### 1.5 Grief Attacks

**Attack:** Spend reputation to harm specific targets rather than profit.

**Mechanism:**
- Build or purchase reputation
- File false challenges against legitimate beliefs
- Spam disputes to waste target's time/reputation
- Coordinate mass downvoting in governance
- Block target from federations through false reports

**Variants:**
- **Targeted grief**: Single victim, sustained harassment
- **Competitive grief**: Damage business competitor's agents
- **Ideological grief**: Attack agents with opposing views
- **State-sponsored grief**: Government suppresses inconvenient information

**Impact:** Chills participation; honest agents avoid network to escape harassment.

---

### 1.6 Free Riding

**Attack:** Extract network value without contributing proportionally.

**Mechanism:**
- Query the network extensively (consume others' beliefs)
- Rarely contribute own beliefs or verifications
- Avoid service provision duties
- Use premium features via reputation earned elsewhere (if portable)
- Extract synthesized knowledge without attribution

**Variants:**
- **Query vampire**: Massive query volume, zero contribution
- **Cherry picker**: Only engage when profitable, never during maintenance
- **Federation hopper**: Move between federations to escape contribution requirements
- **API abuser**: Automated extraction without human-level participation

**Impact:** Network becomes unsustainable; contributors subsidize extractors.

---

### 1.7 Tragedy of Commons

**Attack:** Individual incentive to extract value exceeds incentive to maintain shared resources.

**Mechanism:**
- Overuse shared resources (query capacity, storage)
- Underinvest in public goods (infrastructure, moderation)
- Prioritize short-term extraction over long-term health
- Compete for limited rewards, ignore collective needs

**Variants:**
- **Verification exhaustion**: Verify everything for rewards, ignore quality
- **Domain squatting**: Claim expertise in domains to block competition
- **Dispute farming**: Create disputes for resolution rewards, regardless of merit
- **Network stress**: Push limits of capacity without contributing infrastructure

**Impact:** Network degrades; quality declines; active contributors leave.

---

### 1.8 Market Manipulation

**Attack:** If beliefs affect external markets, exploit information asymmetry for profit.

**Mechanism:**
- Identify beliefs that, if changed, would move external markets
- Accumulate position in external market
- Create/verify beliefs that move market in desired direction
- Profit from market movement
- Accept reputation penalty as cost of doing business

**Variants:**
- **Prediction market manipulation**: Beliefs tied to prediction markets become targets
- **News frontrunning**: Know a contradiction will be published, trade before
- **Belief injection**: Insert false beliefs that traders rely upon
- **Selective revelation**: Delay verifications until after taking market position

**Impact:** External financial incentives overwhelm internal reputation incentives.

---

## 2. Defense Mechanisms

### 2.1 Reputation Velocity Limits

**Defense against:** Farming, Pump and Dump, Collusion Rings

**Mechanism:** Reputation cannot be gained or spent faster than configured limits.

```typescript
VelocityLimits {
  // Earning velocity
  max_daily_gain: 0.02          // 2% max per day
  max_weekly_gain: 0.08         // 8% max per week
  max_monthly_gain: 0.25        // 25% max per month
  max_single_event_gain: 0.03   // 3% max from any single action
  
  // Spending velocity
  max_daily_spend: 0.10         // 10% max per day
  max_single_stake: 0.20        // 20% max on single claim/verification
  
  // Per-activity limits
  verifications_per_hour: 10
  verifications_per_day: 50
  beliefs_per_day: 20
  disputes_per_day: 5
  
  // Cooldowns
  high_stake_cooldown_hours: 24  // After >10% stake, 24h before next
}
```

**Enforcement:**
```typescript
function check_velocity(agent: DID, action: Action): VelocityResult {
  const windows = [
    { period: 'hour', limit: LIMITS[action.type + '_per_hour'] },
    { period: 'day', limit: LIMITS[action.type + '_per_day'] },
    { period: 'week', limit: LIMITS[action.type + '_per_week'] },
  ]
  
  for (const window of windows) {
    const count = count_actions(agent, action.type, window.period)
    if (count >= window.limit) {
      return { allowed: false, reason: `${window.period} limit exceeded`, retry_after: window.end }
    }
  }
  
  const rep_change = estimate_reputation_impact(action)
  if (action.is_gain && rep_change > LIMITS.max_single_event_gain) {
    return { allowed: false, reason: 'single event gain limit', capped_at: LIMITS.max_single_event_gain }
  }
  
  return { allowed: true }
}
```

**Rationale:** Farming requires sustained activity; velocity limits extend time required, increasing detection window. Pump-and-dump is limited because even high-rep accounts can't stake unlimited amounts.

---

### 2.2 Anomaly Detection System

**Defense against:** All attacks (detection layer)

**Mechanism:** Statistical monitoring flags unusual patterns for review.

```typescript
AnomalyDetector {
  monitors: [
    BehaviorMonitor,       // Individual agent patterns
    NetworkMonitor,        // System-wide patterns  
    RelationshipMonitor,   // Agent-agent interaction patterns
    TemporalMonitor,       // Time-based anomalies
    DomainMonitor,         // Domain-specific anomalies
  ]
  
  alert_threshold: 0.8     // Anomaly score triggering review
  auto_action_threshold: 0.95  // Score triggering automatic response
}
```

#### Behavior Monitor (Individual)

Detects deviation from agent's established baseline:

```typescript
BehaviorAnomaly {
  agent: DID
  baseline: AgentBaseline       // Rolling 90-day average
  current: AgentBehavior        // Current period behavior
  anomaly_score: float          // 0-1, higher = more anomalous
  anomaly_type: string[]        // Which dimensions are anomalous
}

function compute_behavior_anomaly(agent: DID): BehaviorAnomaly {
  const baseline = get_baseline(agent, days=90)
  const current = get_current(agent, days=7)
  
  const dimensions = {
    verification_rate: z_score(current.verifications_per_day, baseline.verifications_per_day),
    contradiction_rate: z_score(current.contradiction_ratio, baseline.contradiction_ratio),
    domain_distribution: kl_divergence(current.domain_activity, baseline.domain_activity),
    partner_distribution: kl_divergence(current.verification_partners, baseline.verification_partners),
    time_pattern: z_score(current.activity_times, baseline.activity_times),
    stake_pattern: z_score(current.avg_stake, baseline.avg_stake),
    gain_rate: z_score(current.reputation_gain_rate, baseline.reputation_gain_rate),
  }
  
  const anomaly_score = max(...Object.values(dimensions).map(Math.abs)) / 5  // Normalize
  const anomaly_types = Object.entries(dimensions)
    .filter(([k, v]) => Math.abs(v) > 3)  // >3 standard deviations
    .map(([k, v]) => k)
  
  return { agent, baseline, current, anomaly_score, anomaly_types }
}
```

#### Network Monitor (System-wide)

Detects network-level anomalies:

```typescript
NetworkAnomaly {
  type: 'reputation_inflation' | 'verification_surge' | 'dispute_spike' | 
        'federation_migration' | 'belief_flood' | 'service_degradation'
  severity: float
  affected_scope: FederationID | 'network'
  metrics: Map<string, TimeSeries>
}

function monitor_network(): NetworkAnomaly[] {
  const anomalies = []
  
  // Check reputation inflation
  const total_rep = sum(all_agents.reputation)
  const expected_rep = count(all_agents) * 0.5  // Expected average
  if (total_rep > expected_rep * 1.1) {
    anomalies.push({ type: 'reputation_inflation', severity: (total_rep / expected_rep) - 1 })
  }
  
  // Check verification surge
  const verification_rate = count_verifications(last_hour) / avg_verifications_per_hour
  if (verification_rate > 3) {
    anomalies.push({ type: 'verification_surge', severity: verification_rate / 3 })
  }
  
  // ... other monitors
  
  return anomalies
}
```

#### Relationship Monitor (Collusion Detection)

Graph analysis for suspicious interaction patterns:

```typescript
RelationshipAnomaly {
  type: 'mutual_boosting' | 'isolated_cluster' | 'reputation_flow' | 'coordinated_timing'
  agents: DID[]
  evidence: RelationshipEvidence
  confidence: float
}

function detect_collusion_rings(): RelationshipAnomaly[] {
  const graph = build_verification_graph(period=90_days)
  const anomalies = []
  
  // Detect tight mutual verification
  for (const [a, b] of graph.edges) {
    const a_to_b = count_verifications(a, b)
    const b_to_a = count_verifications(b, a)
    const a_total = count_verifications_by(a)
    const b_total = count_verifications_by(b)
    
    const mutual_ratio = (a_to_b + b_to_a) / (a_total + b_total)
    if (mutual_ratio > 0.2 && a_to_b > 5 && b_to_a > 5) {
      anomalies.push({
        type: 'mutual_boosting',
        agents: [a, b],
        evidence: { mutual_ratio, a_to_b, b_to_a },
        confidence: mutual_ratio * 2  // Higher ratio = higher confidence
      })
    }
  }
  
  // Detect isolated clusters
  const clusters = find_communities(graph)
  for (const cluster of clusters) {
    const internal_edges = count_internal_edges(cluster)
    const external_edges = count_external_edges(cluster)
    const isolation_ratio = internal_edges / (external_edges + 1)
    
    if (isolation_ratio > 10 && cluster.size > 3) {
      anomalies.push({
        type: 'isolated_cluster',
        agents: cluster.members,
        evidence: { isolation_ratio, internal_edges, external_edges },
        confidence: min(1, isolation_ratio / 20)
      })
    }
  }
  
  // Detect reputation flow (laundering indicator)
  for (const agent of agents_with_declining_reputation()) {
    const outgoing_flow = compute_reputation_flow_from(agent)
    const recipients = outgoing_flow.filter(f => f.amount > 0.01)
    
    if (recipients.length <= 3 && sum(recipients.amount) > 0.05) {
      anomalies.push({
        type: 'reputation_flow',
        agents: [agent, ...recipients.map(r => r.recipient)],
        evidence: { total_flow: sum(recipients.amount), recipient_count: recipients.length },
        confidence: sum(recipients.amount) * 5
      })
    }
  }
  
  return anomalies
}
```

---

### 2.3 Reputation Vesting (Time-Lock)

**Defense against:** Farming, Pump and Dump, Collusion Rings

**Mechanism:** Newly earned reputation unlocks gradually over time.

```typescript
ReputationVesting {
  // Vesting schedule
  immediate_ratio: 0.25         // 25% available immediately
  vesting_period_days: 90       // Full vesting over 90 days
  vesting_curve: 'linear'       // or 'cliff', 'exponential'
  
  // Vesting state per agent
  vested_reputation: float      // Fully vested, available for staking
  unvested_reputation: float    // Not yet available
  vesting_schedule: VestingTranche[]
}

VestingTranche {
  amount: float
  earned_at: timestamp
  vests_at: timestamp
  source: 'verification' | 'contribution' | 'calibration' | 'service'
}
```

**Vesting Calculation:**
```typescript
function compute_available_reputation(agent: DID): float {
  const vesting = get_vesting_state(agent)
  const now = current_timestamp()
  
  let available = vesting.vested_reputation
  
  for (const tranche of vesting.vesting_schedule) {
    if (now >= tranche.vests_at) {
      available += tranche.amount
    } else {
      // Partial vesting (linear)
      const elapsed = now - tranche.earned_at
      const total = tranche.vests_at - tranche.earned_at
      const vested_ratio = IMMEDIATE_RATIO + (1 - IMMEDIATE_RATIO) * (elapsed / total)
      available += tranche.amount * vested_ratio
    }
  }
  
  return available
}
```

**Staking Constraint:**
```typescript
function validate_stake(agent: DID, stake_amount: float): boolean {
  const available = compute_available_reputation(agent)
  return stake_amount <= available
}
```

**Rationale:** 
- Farmers can't quickly accumulate usable reputation
- Pump-and-dump requires waiting 90 days, extending detection window
- Collusion rings need sustained coordination over months

---

### 2.4 Reputation Decay

**Defense against:** Farming, Tragedy of Commons, Free Riding

**Mechanism:** Inactive reputation decays; must be maintained through continued good behavior.

```typescript
ReputationDecay {
  // Decay parameters
  decay_start_days: 30          // Days of inactivity before decay starts
  decay_rate_per_month: 0.05    // 5% decay per month of inactivity
  decay_floor: float            // Anchor level (see 4.3 of Incentive SPEC)
  
  // Activity thresholds (any of these prevents decay)
  min_verifications_per_month: 5
  min_contributions_per_month: 1
  min_service_hours_per_month: 10
}
```

**Decay Calculation:**
```typescript
function apply_decay(agent: DID): ReputationAdjustment {
  const last_activity = get_last_meaningful_activity(agent)
  const inactive_days = days_since(last_activity)
  
  if (inactive_days <= DECAY_START_DAYS) {
    return { adjustment: 0 }
  }
  
  const inactive_months = (inactive_days - DECAY_START_DAYS) / 30
  const decay_factor = Math.pow(1 - DECAY_RATE_PER_MONTH, inactive_months)
  const current_rep = agent.reputation.overall
  const floor = compute_anchor_level(agent)
  
  const decayed_rep = Math.max(floor, current_rep * decay_factor)
  const adjustment = decayed_rep - current_rep
  
  return { adjustment, reason: 'inactivity_decay', inactive_months }
}
```

**Activity Definition:**
```typescript
function is_meaningful_activity(action: Action): boolean {
  // Not meaningful: queries, passive reading
  // Meaningful: verifications, contributions, service, governance
  return ['verification', 'contribution', 'service', 'governance_vote', 'dispute_resolution']
    .includes(action.type)
}
```

**Rationale:**
- Farmed reputation decays if not actively maintained
- Prevents "reputation hoarding" by inactive accounts
- Forces continued participation to maintain influence

---

### 2.5 Collusion Detection & Response

**Defense against:** Collusion Rings, Reputation Laundering

**Mechanism:** Graph analysis identifies collusion patterns; coordinated response discounts rewards.

#### Detection Heuristics

```typescript
CollusionSignals {
  // Strong signals (each alone is suspicious)
  mutual_verification_rate > 0.15      // >15% of verifications are mutual
  cluster_isolation_ratio > 10         // Internal edges 10x external
  temporal_correlation > 0.8           // Actions within minutes of each other
  
  // Medium signals (suspicious in combination)
  shared_ip_or_infrastructure          // Same node, similar fingerprints
  joined_within_same_week              // Account creation clustering
  identical_domain_distribution        // Exactly same domain expertise
  
  // Weak signals (context-dependent)
  consistent_agreement_rate > 0.95     // Always agree with each other
  no_cross_verification_outside        // Never verify anyone else
  reputation_trajectory_correlation    // Rep rises/falls together
}

function compute_collusion_score(cluster: DID[]): float {
  let score = 0
  
  // Strong signals
  if (mutual_verification_rate(cluster) > 0.15) score += 0.4
  if (cluster_isolation_ratio(cluster) > 10) score += 0.3
  if (temporal_correlation(cluster) > 0.8) score += 0.3
  
  // Medium signals  
  if (shared_infrastructure(cluster)) score += 0.2
  if (joined_same_week(cluster)) score += 0.15
  if (identical_domains(cluster)) score += 0.15
  
  // Weak signals
  if (agreement_rate(cluster) > 0.95) score += 0.1
  if (external_verification_rate(cluster) < 0.1) score += 0.1
  if (trajectory_correlation(cluster) > 0.9) score += 0.1
  
  return min(1.0, score)
}
```

#### Response Mechanism

```typescript
CollusionResponse {
  // Graduated response based on collusion score
  thresholds: {
    0.3: 'monitoring',           // Increased scrutiny, no action
    0.5: 'reward_discount',      // 50% reward reduction for mutual activity
    0.7: 'reputation_freeze',    // Temporary freeze pending investigation
    0.9: 'penalty',              // Immediate reputation penalty
  }
}

function apply_collusion_response(cluster: DID[], score: float): void {
  if (score >= 0.9) {
    // Immediate penalty
    for (const agent of cluster) {
      apply_penalty(agent, {
        amount: 0.1,  // 10% penalty
        reason: 'collusion_detected',
        evidence: compute_collusion_evidence(cluster),
        appealable: true
      })
    }
    // Flag for human review
    create_review_case('collusion', cluster, score)
  }
  
  else if (score >= 0.7) {
    // Freeze reputation changes
    for (const agent of cluster) {
      freeze_reputation(agent, {
        type: 'both',
        duration_hours: 72,
        reason: 'collusion_investigation',
        auto_unfreeze: score < 0.7  // Unfreeze if score drops
      })
    }
  }
  
  else if (score >= 0.5) {
    // Discount rewards for cluster members
    for (const agent of cluster) {
      set_reward_modifier(agent, {
        factor: 0.5,
        applies_to: cluster,  // Only for interactions with cluster members
        duration: 'until_score_drops'
      })
    }
  }
  
  else if (score >= 0.3) {
    // Monitoring only
    increase_monitoring(cluster)
  }
}
```

#### Ring Discount Formula

Mutual verifications are discounted based on relationship history:

```typescript
function compute_verification_reward(verifier: DID, holder: DID, base_reward: float): float {
  const mutual_history = get_mutual_verification_history(verifier, holder)
  const verifier_total = get_total_verifications(verifier)
  const holder_total = get_total_verifications_received(holder)
  
  // Compute ring coefficient
  const ring_coefficient = mutual_history.count / Math.min(verifier_total, holder_total)
  
  // Discount factor decreases with ring coefficient
  const discount = 1 / (1 + ring_coefficient * 5)  // Heavy penalty for mutual activity
  
  return base_reward * discount
}
```

---

### 2.6 Contribution Diversity Requirements

**Defense against:** Farming, Gaming Specialization

**Mechanism:** Rewards require diverse activity; can't specialize in one easily-gamed vector.

```typescript
DiversityRequirements {
  // Minimum activity distribution for full rewards
  min_domains: 3                // Must be active in 3+ domains
  max_domain_concentration: 0.6 // No domain >60% of activity
  
  min_activity_types: 2         // Must do 2+ activity types
  max_activity_concentration: 0.8  // No activity >80% of total
  
  min_unique_partners: 10       // Must interact with 10+ unique agents
  max_partner_concentration: 0.2   // No partner >20% of interactions
}

function compute_diversity_score(agent: DID): float {
  const activity = get_activity_distribution(agent, days=90)
  
  // Domain diversity
  const domain_entropy = compute_entropy(activity.by_domain)
  const domain_score = min(1, domain_entropy / log(3))  // Normalized to 3 domains
  
  // Activity type diversity
  const type_entropy = compute_entropy(activity.by_type)
  const type_score = min(1, type_entropy / log(2))  // Normalized to 2 types
  
  // Partner diversity
  const partner_entropy = compute_entropy(activity.by_partner)
  const partner_score = min(1, partner_entropy / log(10))  // Normalized to 10 partners
  
  return (domain_score + type_score + partner_score) / 3
}

function apply_diversity_modifier(agent: DID, base_reward: float): float {
  const diversity = compute_diversity_score(agent)
  
  if (diversity < 0.3) {
    // Severe penalty for extreme concentration
    return base_reward * 0.25
  } else if (diversity < 0.5) {
    // Moderate penalty
    return base_reward * 0.5
  } else if (diversity < 0.7) {
    // Minor penalty
    return base_reward * 0.8
  } else {
    // Full reward (or bonus for high diversity)
    return base_reward * (0.8 + diversity * 0.4)  // Up to 1.12x for perfect diversity
  }
}
```

---

### 2.7 Stake-Weighted Verification Queues

**Defense against:** Grief Attacks, Spam

**Mechanism:** Verification and dispute requests are prioritized by stake, making spam expensive.

```typescript
VerificationQueue {
  // Queue priority = stake * urgency * reputation
  priority_formula: (stake, urgency, reputation) => stake * urgency * sqrt(reputation)
  
  // Minimum stakes by action type
  min_stakes: {
    verification: 0.01,         // 1% minimum to verify
    challenge: 0.02,            // 2% minimum to challenge
    dispute: 0.05,              // 5% minimum to escalate to dispute
    governance_proposal: 0.10,  // 10% minimum to propose changes
  }
  
  // Grief attack mitigation
  failed_challenge_penalty: 2.0  // Lose 2x stake on failed challenge
  spam_threshold: 5             // >5 failed challenges = escalated penalty
}
```

**Anti-Grief Logic:**
```typescript
function handle_challenge_result(challenger: DID, challenge: Challenge, outcome: 'upheld' | 'rejected'): void {
  if (outcome === 'rejected') {
    // Challenger was wrong
    const base_penalty = challenge.stake
    
    // Check for grief pattern
    const recent_failures = count_failed_challenges(challenger, days=30)
    
    if (recent_failures > SPAM_THRESHOLD) {
      // Escalated penalty for serial griefers
      const escalation = 1 + (recent_failures - SPAM_THRESHOLD) * 0.5
      apply_penalty(challenger, base_penalty * FAILED_CHALLENGE_PENALTY * escalation)
      
      // Temporary challenge cooldown
      set_cooldown(challenger, 'challenge', hours=24 * recent_failures)
    } else {
      apply_penalty(challenger, base_penalty * FAILED_CHALLENGE_PENALTY)
    }
  } else {
    // Challenger was right - reward
    reward_challenger(challenger, challenge)
  }
}
```

---

### 2.8 External Value Firewall

**Defense against:** Market Manipulation, Pump and Dump

**Mechanism:** Beliefs affecting high-value external decisions face additional scrutiny.

```typescript
ExternalValueFirewall {
  // Classification of belief impact
  impact_levels: {
    low: 'internal_only',       // Only affects network operations
    medium: 'external_informational',  // May inform external decisions
    high: 'external_financial', // Directly affects financial instruments
    critical: 'external_safety' // Affects safety-critical systems
  }
  
  // Additional requirements by impact level
  requirements: {
    low: { min_verifications: 1, min_verifier_rep: 0.3 },
    medium: { min_verifications: 3, min_verifier_rep: 0.5, cooling_period_hours: 6 },
    high: { min_verifications: 5, min_verifier_rep: 0.7, cooling_period_hours: 24, diversity_required: true },
    critical: { min_verifications: 10, min_verifier_rep: 0.8, cooling_period_hours: 72, human_review: true }
  }
}
```

**Market-Sensitive Belief Detection:**
```typescript
function classify_belief_impact(belief: Belief): ImpactLevel {
  const signals = {
    mentions_financial_instrument: detect_financial_entities(belief.content),
    references_market_data: detect_market_references(belief.content),
    domain_is_financial: belief.domains.includes('finance') || belief.domains.includes('economics'),
    holder_has_market_access: check_holder_market_access(belief.holder),
    timing_near_market_hours: is_near_market_hours(belief.created_at),
  }
  
  const risk_score = 
    (signals.mentions_financial_instrument ? 0.4 : 0) +
    (signals.references_market_data ? 0.3 : 0) +
    (signals.domain_is_financial ? 0.2 : 0) +
    (signals.holder_has_market_access ? 0.1 : 0) +
    (signals.timing_near_market_hours ? 0.1 : 0)
  
  if (risk_score > 0.7) return 'high'
  if (risk_score > 0.4) return 'medium'
  return 'low'
}
```

**Cooling Period Enforcement:**
```typescript
function can_belief_affect_decisions(belief: Belief): boolean {
  const impact = classify_belief_impact(belief)
  const requirements = FIREWALL_REQUIREMENTS[impact]
  
  const verifications = get_verifications(belief)
  const age_hours = hours_since(belief.created_at)
  
  // Check cooling period
  if (age_hours < requirements.cooling_period_hours) {
    return false  // Too new, cannot be relied upon
  }
  
  // Check verification count
  if (verifications.length < requirements.min_verifications) {
    return false
  }
  
  // Check verifier quality
  const qualified_verifiers = verifications.filter(v => 
    v.verifier.reputation >= requirements.min_verifier_rep
  )
  if (qualified_verifiers.length < requirements.min_verifications) {
    return false
  }
  
  // Check diversity if required
  if (requirements.diversity_required) {
    const unique_federations = new Set(qualified_verifiers.map(v => v.verifier.federation))
    if (unique_federations.size < 3) {
      return false
    }
  }
  
  return true
}
```

---

### 2.9 Retroactive Clawback

**Defense against:** All attacks (post-hoc justice)

**Mechanism:** Even successful attacks face reputation recovery once detected.

```typescript
Clawback {
  // Clawback triggers
  triggers: [
    'collusion_confirmed',      // Investigation confirms collusion
    'fraud_proven',             // Deliberate false claim proven
    'market_manipulation',      // External manipulation detected
    'identity_compromise',      // Account takeover detected
  ]
  
  // Clawback parameters
  lookback_period_days: 365     // Can claw back up to 1 year
  max_clawback_ratio: 0.5       // Max 50% of historical gains
  
  // Evidence requirements
  evidence_threshold: 'clear_and_convincing'  // Not beyond reasonable doubt
}

ClawbackOrder {
  target: DID
  period: [timestamp, timestamp]
  affected_transactions: UUID[]
  total_clawback: float
  evidence: Evidence[]
  issued_by: DID                // Governance authority
  appeal_deadline: timestamp
  status: 'pending' | 'executed' | 'appealed' | 'reversed'
}
```

**Clawback Execution:**
```typescript
async function execute_clawback(order: ClawbackOrder): Promise<void> {
  // Identify affected transactions
  const transactions = await get_transactions(order.target, order.period)
  
  // Compute ill-gotten gains
  const suspicious = transactions.filter(t => is_affected_by(t, order.evidence))
  const gains = sum(suspicious.filter(t => t.type === 'reward').map(t => t.amount))
  
  // Apply clawback (capped)
  const clawback_amount = min(gains, order.target.reputation * MAX_CLAWBACK_RATIO)
  
  // Reduce reputation
  apply_penalty(order.target, clawback_amount, {
    reason: 'clawback',
    evidence: order.evidence,
    appealable: true
  })
  
  // Redistribute to victims if identifiable
  const victims = identify_victims(order.evidence)
  if (victims.length > 0) {
    const per_victim = clawback_amount * 0.8 / victims.length  // 80% to victims, 20% burned
    for (const victim of victims) {
      award_reputation(victim, per_victim, { reason: 'clawback_redistribution' })
    }
  }
  
  // Record for transparency
  publish_clawback_record(order)
}
```

---

## 3. Detection Heuristics Summary

### 3.1 Per-Attack Detection Matrix

| Attack | Primary Signals | Secondary Signals | Detection Confidence |
|--------|-----------------|-------------------|---------------------|
| **Farming** | Low stake, high volume | Easy beliefs only, no contradictions | Medium |
| **Laundering** | Reputation outflow pattern | New identity correlated with old | High |
| **Pump & Dump** | Sudden high-stake action | External market timing | Medium-High |
| **Collusion** | Mutual verification, clustering | Temporal correlation, same infra | High |
| **Grief** | High challenge failure rate | Target concentration | High |
| **Free Riding** | Query/contribution imbalance | No service provision | High |
| **Tragedy** | Resource overconsumption | Public good underinvestment | Medium |
| **Market Manipulation** | Financial belief timing | External position evidence | Low-Medium |

### 3.2 Detection Confidence Levels

```typescript
DetectionConfidence {
  high: 0.8+     // Automated response appropriate
  medium: 0.5-0.8 // Human review recommended
  low: 0.3-0.5   // Monitoring only
  noise: <0.3    // Likely false positive
}
```

### 3.3 False Positive Mitigation

```typescript
FalsePositiveMitigation {
  // Two-phase detection
  phase1: 'automated_flagging'   // Fast, may have false positives
  phase2: 'human_review'         // Slower, high accuracy
  
  // Reputation protection
  no_penalty_without_review: true  // No auto-penalties for scores <0.9
  appeal_process: true             // All penalties appealable
  compensation_for_false_positive: 0.02  // 2% reputation for wrongful flag
  
  // Learning from mistakes
  false_positive_feedback: true    // Update models on appeals
}
```

---

## 4. Penalty Structures

### 4.1 Graduated Penalty Scale

```typescript
PenaltyScale {
  // Severity levels
  warning: {
    reputation_impact: 0,
    effects: ['monitoring_increased', 'notification_sent'],
    duration: null,
    appeal: false
  },
  
  minor: {
    reputation_impact: 0.01-0.05,
    effects: ['reward_reduction_30d'],
    duration: '30d',
    appeal: true
  },
  
  moderate: {
    reputation_impact: 0.05-0.15,
    effects: ['reward_reduction_90d', 'stake_limit_50%'],
    duration: '90d',
    appeal: true
  },
  
  severe: {
    reputation_impact: 0.15-0.25,
    effects: ['reward_suspension_180d', 'governance_excluded'],
    duration: '180d',
    appeal: true,
    human_review_required: true
  },
  
  ban: {
    reputation_impact: 'to_minimum',
    effects: ['network_exclusion'],
    duration: 'permanent',
    appeal: true,
    governance_vote_required: true
  }
}
```

### 4.2 Attack-Specific Penalties

| Attack | First Offense | Repeat Offense | Organized/Large-Scale |
|--------|--------------|----------------|----------------------|
| **Farming** | Minor | Moderate | Severe |
| **Laundering** | Moderate | Severe | Ban |
| **Pump & Dump** | Severe | Ban | Ban + Clawback |
| **Collusion (participant)** | Minor | Moderate | Severe |
| **Collusion (organizer)** | Severe | Ban | Ban + Clawback |
| **Grief** | Minor | Severe | Ban |
| **Free Riding** | Warning | Minor | Moderate |
| **Market Manipulation** | Severe | Ban | Ban + External referral |

### 4.3 Penalty Modifiers

```typescript
PenaltyModifiers {
  // Aggravating factors (increase penalty)
  aggravating: {
    repeated_offense: 1.5,        // Each repeat adds 50%
    organized_ring: 2.0,          // Part of coordinated attack
    external_profit: 2.0,         // Evidence of external gain
    targeting_vulnerable: 1.5,   // Attacked new/low-rep agents
    during_crisis: 1.5,          // During network stress event
  },
  
  // Mitigating factors (reduce penalty)
  mitigating: {
    self_reported: 0.5,          // Came forward voluntarily
    first_time: 0.75,            // No prior offenses
    cooperated: 0.6,             // Helped investigation
    accidental: 0.5,             // Genuinely unintentional
    restitution: 0.7,            // Made victims whole
  }
}
```

### 4.4 Recovery Path

```typescript
RecoveryPath {
  // Agents can recover from penalties through positive behavior
  
  // After minor penalty
  minor_recovery: {
    duration: '90d',
    requirements: [
      'no_further_violations',
      'positive_contribution_score > 0.5',
      'diversity_score > 0.6'
    ],
    outcome: 'penalty_expunged'
  },
  
  // After moderate penalty
  moderate_recovery: {
    duration: '180d',
    requirements: [
      'no_further_violations',
      'positive_contribution_score > 0.7',
      'diversity_score > 0.7',
      'community_service_hours > 20'  // Dispute resolution, etc.
    ],
    outcome: 'reputation_restored_50%'
  },
  
  // After severe penalty
  severe_recovery: {
    duration: '365d',
    requirements: [
      'no_further_violations',
      'positive_contribution_score > 0.8',
      'external_vouching',           // Other high-rep agents vouch
      'governance_review_passed'
    ],
    outcome: 'reputation_restored_25%'
  }
}
```

---

## 5. Implementation Priorities

### 5.1 Phase 1: Core Defenses (Essential)

1. **Velocity limits** — Simple, effective, low implementation cost
2. **Basic anomaly detection** — Behavior monitoring for obvious outliers
3. **Reputation decay** — Prevents passive accumulation
4. **Stake requirements** — Every action has cost

### 5.2 Phase 2: Graph Analysis (High Value)

5. **Collusion detection** — Graph-based ring detection
6. **Relationship monitoring** — Mutual verification tracking
7. **Diversity requirements** — Prevent specialization gaming

### 5.3 Phase 3: Advanced Protection (Sophisticated)

8. **Vesting schedules** — Time-locked reputation
9. **External value firewall** — Market manipulation protection
10. **Retroactive clawback** — Post-hoc justice system

### 5.4 Phase 4: Continuous Improvement

11. **ML-based anomaly detection** — Learn attack patterns
12. **Cross-federation coordination** — Network-wide threat response
13. **Economic simulation** — Model new attacks before they occur

---

## 6. Remaining Risks

### 6.1 Biggest Remaining Risk: External Value Extraction

**The Problem:** If beliefs in Valence can move external markets (prediction markets, financial instruments, business decisions), the external value at stake may dwarf the internal reputation at risk.

**Example:** An agent with 0.8 reputation makes a false claim that moves a $1B market by 0.1%. They profit $1M externally while losing only reputation internally. The attack is wildly profitable.

**Mitigations in place:**
- External value firewall (cooling periods, additional verification)
- Market-sensitive belief detection
- Clawback mechanisms

**Residual risk:** A sophisticated actor with sufficient resources can:
- Build genuine reputation over years
- Time attack perfectly with market positions
- Accept total reputation loss as cost of doing business
- Operate through jurisdictions that don't cooperate with investigations

**Honest assessment:** This is fundamentally a hard problem. When external stakes exceed internal stakes, no internal incentive system can fully prevent exploitation. Mitigations reduce probability and impact, but cannot eliminate the risk.

### 6.2 State-Level Adversaries

**The Problem:** Nation-states have effectively unlimited resources and can coordinate attacks that appear organic.

**Residual risk:**
- Can create thousands of seemingly-independent identities
- Can sustain long-term reputation building
- Can coordinate without leaving detectable patterns
- May control significant network infrastructure

**Mitigation:** Focus on making attacks expensive and detectable, accepting that determined state actors may succeed at high cost.

### 6.3 Unknown Attack Vectors

**The Problem:** This taxonomy covers known attacks. Novel attacks will emerge.

**Mitigation:** 
- Anomaly detection catches unusual patterns even without specific attack signatures
- Economic simulation can model hypothetical attacks
- Bug bounty for novel attack discovery
- Continuous monitoring and rapid response capability

### 6.4 Social Engineering

**The Problem:** Attacks that manipulate human operators rather than the system itself.

**Example:** Convincing a federation admin that a legitimate high-rep agent is actually an attacker, triggering wrongful penalties.

**Mitigation:**
- Multi-sig for severe actions
- Appeal processes
- Transparency in penalty decisions
- Separation of duties

---

## 7. Monitoring & Alerting

### 7.1 Real-Time Dashboards

```typescript
SecurityDashboard {
  // Network health
  total_reputation: TimeSeries
  verification_rate: TimeSeries
  dispute_rate: TimeSeries
  
  // Attack indicators
  collusion_score_distribution: Histogram
  anomaly_alerts: List<Alert>
  velocity_violations: List<Violation>
  
  // Response status
  active_investigations: number
  pending_penalties: number
  recent_clawbacks: List<Clawback>
}
```

### 7.2 Alert Thresholds

```typescript
AlertThresholds {
  // Immediate alerts (page on-call)
  immediate: [
    'network_wide_anomaly_score > 0.9',
    'verification_rate_spike > 5x_baseline',
    'dispute_rate_spike > 10x_baseline',
    'large_reputation_transfer > 10%',
  ],
  
  // Urgent alerts (respond within 4 hours)
  urgent: [
    'collusion_ring_detected_size > 10',
    'single_agent_anomaly > 0.95',
    'market_sensitive_belief_unverified',
  ],
  
  // Standard alerts (next business day)
  standard: [
    'collusion_ring_detected_size > 3',
    'single_agent_anomaly > 0.8',
    'velocity_violation_pattern',
  ]
}
```

---

## 8. Summary

### Attacks Covered

| Attack | Prevention | Detection | Response |
|--------|------------|-----------|----------|
| Reputation Farming | Velocity limits, vesting, decay | Behavior anomaly, diversity score | Reward discount, penalty |
| Reputation Laundering | Vesting, transfer limits | Graph analysis, flow detection | Clawback, identity link |
| Pump and Dump | Vesting, external firewall | Market timing correlation | Severe penalty, clawback |
| Collusion Rings | Ring discount, diversity req | Graph clustering, mutual rate | Graduated response, penalty |
| Grief Attacks | Stake requirements, queue priority | Failed challenge rate | Escalating cooldowns, penalty |
| Free Riding | Decay, contribution requirements | Query/contribution imbalance | Access restrictions |
| Tragedy of Commons | Decay, diversity requirements | Resource consumption monitoring | Rate limiting |
| Market Manipulation | External firewall, cooling periods | Financial entity detection | Severe penalty, external referral |

### Defense Layers

1. **Economic deterrence** — Attacks cost more than honest participation
2. **Rate limiting** — Velocity limits prevent rapid exploitation
3. **Time locking** — Vesting prevents quick reputation deployment
4. **Graph analysis** — Collusion detection through relationship patterns
5. **Anomaly detection** — Statistical monitoring catches unusual behavior
6. **Graduated response** — Penalties scale with severity
7. **Retroactive justice** — Clawback for discovered attacks
8. **Transparency** — Public accountability for all penalty decisions

### Biggest Remaining Risk

**External value extraction** — When external profits exceed internal reputation at risk, attacks may be economically rational despite defenses. No internal incentive system can fully prevent exploitation when external stakes are sufficiently high. Mitigations reduce but cannot eliminate this fundamental tension.

---

*"Security is not a feature; it's a property that emerges from thousands of small design decisions. Make each one count."*
