# Consensus Node Selection — Specification

*"Whoever selects the validators controls truth. Selection must be beyond any single party's control."*

---

## Overview

This specification defines how **consensus nodes** are selected in Valence—the agents authorized to validate L4 (Communal Knowledge) elevation. This addresses the critical gap identified in the threat model: without defined selection, Byzantine consensus provides no security guarantee.

**Design goals:**
- **Sybil-resistant**: Creating fake identities doesn't help capture consensus
- **Decentralized**: No single entity controls selection
- **Stake-weighted**: Validators have skin in the game
- **Rotational**: Prevents power entrenchment
- **Transparent**: Selection process is publicly verifiable

---

## 1. Consensus Node Roles

### 1.1 Validator Set

The **active validator set** consists of agents authorized to participate in consensus for a given **epoch** (7-day period).

```typescript
ValidatorSet {
  epoch: uint64                      // Epoch number
  epoch_start: timestamp
  epoch_end: timestamp
  
  validators: Validator[]            // Active validators for this epoch
  validator_count: uint64            // n = 3f+1 where f = max byzantine
  quorum_threshold: uint64           // 2f+1 required for consensus
  
  // Selection proof
  selection_seed: bytes32            // VRF-derived randomness for this epoch
  selection_proof: VRFProof          // Verifiable proof of fair selection
  
  // Previous epoch reference (chain of epochs)
  previous_epoch_hash: bytes32
}

Validator {
  agent_id: DID
  
  // Stake
  staked_reputation: float           // Reputation locked for this epoch
  stake_lock_until: timestamp        // Cannot withdraw until epoch ends + buffer
  
  // Selection
  selection_weight: float            // Probability weight when selected
  selection_ticket: bytes32          // VRF ticket that won selection
  
  // Performance (updated throughout epoch)
  participation_rate: float          // % of consensus rounds participated
  byzantine_strikes: uint64          // Detected misbehavior count
  
  // Eligibility metadata
  reputation_at_selection: float     // Snapshot at selection time
  federation_membership: string[]    // For diversity requirements
  tenure_epochs: uint64              // How many consecutive epochs served
}
```

### 1.2 Validator Lifecycle

```
┌─────────────┐     Stake &      ┌─────────────┐    Selected     ┌─────────────┐
│   ELIGIBLE  │ ──────────────── │   STAKED    │ ─────────────── │   ACTIVE    │
│  (meets     │   Registration   │  (in pool   │    by VRF       │ (validating │
│   criteria) │                  │   for next  │                 │  this epoch)│
└─────────────┘                  │   epoch)    │                 └──────┬──────┘
      ▲                          └─────────────┘                        │
      │                                 │                               │
      │                                 │ Not selected                  │ Epoch ends
      │                                 │ (remains in pool)             │
      │                                 ▼                               ▼
      │                          ┌─────────────┐                 ┌─────────────┐
      │                          │   STAKED    │                 │  COOLDOWN   │
      │                          │  (waiting)  │                 │ (unbonding) │
      │                          └─────────────┘                 └──────┬──────┘
      │                                                                 │
      │◄────────────────────────────────────────────────────────────────┘
               After cooldown period (14 days), stake unlocked
```

---

## 2. Eligibility Requirements

### 2.1 Base Eligibility

To be eligible for consensus node selection, an agent MUST meet ALL of:

| Requirement | Threshold | Rationale |
|-------------|-----------|-----------|
| **Reputation** | ≥ 0.5 | Demonstrated network participation |
| **Account Age** | ≥ 180 days | Resist Sybil fast-cycling |
| **Verification History** | ≥ 50 verifications | Proven epistemic engagement |
| **Uphold Rate** | ≥ 70% | Verifications that weren't challenged/overturned |
| **No Active Slashing** | 0 unresolved | Not currently penalized |
| **Identity Attestation** | Required | At least one form (see §2.2) |

### 2.2 Identity Attestation (Anti-Sybil)

Validators MUST have at least ONE of the following attestations bound to their DID:

1. **Social Attestation**: Verified by 3+ existing validators (each attests "I know this is a distinct person")
2. **Federation Vouching**: Active member of 2+ established federations (each >1 year old, >50 members)
3. **External Attestation**: Bridge from external identity system (government ID, Worldcoin, BrightID, etc.)
4. **Proof of Unique Human**: Biometric or cryptographic personhood proof

```typescript
IdentityAttestation {
  type: AttestationType
  attestation_id: UUID
  attester: DID | 'external_system'
  attested_at: timestamp
  expires_at?: timestamp
  
  // Verification
  proof: bytes                       // Cryptographic proof appropriate to type
  verifiable: boolean                // Can third parties verify?
}

enum AttestationType {
  SOCIAL_VALIDATOR = 'social_validator'      // Existing validators vouch
  FEDERATION_MEMBER = 'federation_member'    // Federation vouches
  GOVERNMENT_ID = 'government_id'            // Via bridge
  BIOMETRIC_POH = 'biometric_poh'            // Worldcoin, etc.
  WEB_OF_TRUST = 'web_of_trust'              // Keybase-style
}
```

**Attestation Requirements for Validator Eligibility:**
- At least 1 attestation required
- Multiple attestations increase selection weight (see §3.2)
- Attestations expire (social: 1 year, external: per provider policy)
- Lost attestations → immediate eligibility suspension

### 2.3 Stake Requirements

To enter the selection pool, agents must **stake** reputation:

| Validator Tier | Min Stake | Max Stake | Selection Weight Multiplier |
|----------------|-----------|-----------|------------------------------|
| **Standard** | 0.10 | 0.30 | 1.0× |
| **Enhanced** | 0.30 | 0.50 | 1.5× |
| **Guardian** | 0.50 | 0.80 | 2.0× |

**Stake mechanics:**
- Staked reputation is LOCKED and cannot be used elsewhere
- Stake is at risk of slashing (see §6)
- Higher stake = higher selection probability AND higher slashing risk
- Stake must be maintained for entire epoch + 14-day cooldown

```typescript
StakeRegistration {
  agent_id: DID
  amount: float                      // Reputation to stake
  tier: ValidatorTier
  
  // Timing
  registered_at: timestamp
  eligible_from_epoch: uint64        // Can't join current epoch
  
  // Status
  status: StakeStatus                // PENDING | ACTIVE | UNBONDING | SLASHED
  unbond_requested_at?: timestamp
  unbond_available_at?: timestamp
}
```

---

## 3. Selection Algorithm

### 3.1 VRF-Based Random Selection

Selection uses **Verifiable Random Functions** to ensure unpredictable but verifiable randomness.

```typescript
// Each epoch's randomness is derived from previous epoch + block hash
function deriveEpochSeed(previousEpoch: ValidatorSet, blockHash: bytes32): bytes32 {
  return SHA256(
    previousEpoch.selection_seed ||
    blockHash ||
    DOMAIN_SEPARATOR_EPOCH_SEED
  )
}

// Each staked agent computes their VRF ticket
function computeSelectionTicket(
  agent: DID,
  privateKey: Ed25519PrivateKey,
  epochSeed: bytes32
): { ticket: bytes32, proof: VRFProof } {
  // VRF output is deterministic but unpredictable without private key
  const input = SHA256(epochSeed || agent.fingerprint)
  const { output, proof } = VRF.prove(privateKey, input)
  return { ticket: output, proof }
}

// Selection: tickets below threshold are selected
function selectValidators(
  candidates: StakedCandidate[],
  epochSeed: bytes32,
  targetCount: uint64
): Validator[] {
  
  // Each candidate computes their ticket
  const withTickets = candidates.map(c => ({
    ...c,
    ticket: computeSelectionTicket(c.agent_id, c.proof.publicKey, epochSeed),
    weight: computeSelectionWeight(c)
  }))
  
  // Sort by ticket (VRF output ensures uniform distribution)
  withTickets.sort((a, b) => a.ticket.compare(b.ticket))
  
  // Apply diversity constraints (see §3.3)
  const diverse = applyDiversityConstraints(withTickets, targetCount)
  
  // Select top N after diversity filtering
  return diverse.slice(0, targetCount)
}
```

### 3.2 Selection Weight Calculation

Selection probability is proportional to weight:

```python
def compute_selection_weight(candidate: StakedCandidate) -> float:
    """
    Compute candidate's selection weight.
    Higher weight = higher probability of selection.
    """
    
    # Base: stake tier multiplier
    base = candidate.tier.multiplier  # 1.0, 1.5, or 2.0
    
    # Reputation bonus (beyond minimum)
    rep_excess = max(0, candidate.reputation - 0.5)
    reputation_factor = 1.0 + (rep_excess * 0.5)  # Up to 1.25× at rep=1.0
    
    # Attestation bonus
    attestation_count = len(candidate.attestations)
    attestation_factor = 1.0 + (0.1 * min(attestation_count, 3))  # Up to 1.3×
    
    # Tenure penalty (anti-entrenchment)
    consecutive_epochs = candidate.tenure_epochs
    if consecutive_epochs > 4:
        tenure_penalty = 0.9 ** (consecutive_epochs - 4)  # Decreasing after 4 epochs
    else:
        tenure_penalty = 1.0
    
    # Recent performance bonus (if previously served)
    if candidate.last_epoch_performance:
        perf = candidate.last_epoch_performance
        performance_factor = 0.9 + (0.2 * perf.participation_rate)  # 0.9-1.1×
    else:
        performance_factor = 1.0  # New validators: neutral
    
    return base * reputation_factor * attestation_factor * tenure_penalty * performance_factor
```

### 3.3 Diversity Constraints

To prevent capture by coordinated groups, selection enforces diversity:

```typescript
DiversityConstraints {
  // Federation diversity
  max_from_same_federation: uint64       // No more than 20% from any federation
  min_federation_diversity: uint64       // At least N different federations represented
  
  // Tenure diversity
  max_consecutive_validators: float      // Max 60% can be returning from last epoch
  min_new_validators: float              // At least 20% must be new this epoch
  
  // Reputation diversity
  min_standard_tier: float               // At least 30% from standard tier
  
  // Geographic diversity (if attestations include location)
  max_from_same_region?: float           // Optional: regional limits
}

function applyDiversityConstraints(
  candidates: WeightedCandidate[],
  targetCount: uint64
): WeightedCandidate[] {
  const selected: WeightedCandidate[] = []
  const federationCounts: Map<string, number> = new Map()
  let returningCount = 0
  let newCount = 0
  
  for (const candidate of candidates) {
    // Check federation limit
    const maxPerFed = Math.ceil(targetCount * 0.2)
    for (const fed of candidate.federation_membership) {
      if ((federationCounts.get(fed) || 0) >= maxPerFed) {
        continue  // Skip this candidate
      }
    }
    
    // Check returning validator limit
    if (candidate.tenure_epochs > 0) {
      if (returningCount >= targetCount * 0.6) {
        continue  // Too many returning validators
      }
      returningCount++
    } else {
      newCount++
    }
    
    // Accept candidate
    selected.push(candidate)
    for (const fed of candidate.federation_membership) {
      federationCounts.set(fed, (federationCounts.get(fed) || 0) + 1)
    }
    
    if (selected.length >= targetCount) break
  }
  
  // Verify minimum new validator requirement
  if (newCount < targetCount * 0.2) {
    // Force-fill with new validators from remaining pool
    // ... implementation details
  }
  
  return selected
}
```

---

## 4. Validator Set Size

### 4.1 Dynamic Sizing

Validator set size scales with network size and elevation volume:

```typescript
function computeValidatorSetSize(networkStats: NetworkStats): uint64 {
  // Base: 3f+1 where f = max byzantine nodes to tolerate
  // For practical security, f should be at least 10
  const MIN_VALIDATORS = 31  // 3*10+1
  const MAX_VALIDATORS = 100
  
  // Scale with network activity
  const baseSize = MIN_VALIDATORS
  
  // Add 1 validator per 1000 active agents (capped)
  const activityBonus = Math.floor(networkStats.monthly_active_agents / 1000)
  
  // Add 1 validator per 100 L4 elevations last epoch
  const elevationBonus = Math.floor(networkStats.l4_elevations_last_epoch / 100)
  
  const computed = baseSize + activityBonus + elevationBonus
  
  // Ensure 3f+1 format
  const f = Math.floor((Math.min(computed, MAX_VALIDATORS) - 1) / 3)
  return 3 * f + 1
}
```

### 4.2 Quorum Requirements

| Validator Count (n) | Byzantine Tolerance (f) | Quorum (2f+1) | Super-majority (5f/6+1) |
|---------------------|-------------------------|---------------|-------------------------|
| 31 | 10 | 21 | 26 |
| 46 | 15 | 31 | 39 |
| 61 | 20 | 41 | 51 |
| 100 | 33 | 67 | 83 |

---

## 5. Epoch Transitions

### 5.1 Timeline

```
Epoch N                          Epoch N+1
├────────────────────────────────┼────────────────────────────────┤
│                                │                                │
│  Day 1-5: Normal operation     │  Day 1-5: Normal operation     │
│                                │                                │
│  Day 5: Registration closes    │                                │
│         for Epoch N+1          │                                │
│                                │                                │
│  Day 6: Selection computed     │                                │
│         Results published      │                                │
│                                │                                │
│  Day 7: Handoff preparation    │                                │
│         New validators sync    │                                │
│                                │                                │
└────────────────────────────────┴────────────────────────────────┘
```

### 5.2 Transition Protocol

```typescript
interface EpochTransition {
  ending_epoch: uint64
  starting_epoch: uint64
  
  // Outgoing
  outgoing_validators: DID[]
  outgoing_performance: Map<DID, ValidatorPerformance>
  
  // Incoming
  incoming_validators: DID[]
  selection_proof: VRFProof
  
  // State handoff
  pending_elevations: UUID[]      // In-progress consensus rounds
  pending_challenges: UUID[]      // Challenges being reviewed
  
  // Signatures
  outgoing_signatures: Signature[] // 2f+1 outgoing validators sign handoff
  incoming_acknowledgments: Signature[] // Incoming validators confirm receipt
}
```

### 5.3 Pending Consensus Handoff

For elevation votes in progress during transition:

1. **If quorum reached before transition**: Finalize with old validator set
2. **If <50% votes**: Restart with new validator set
3. **If ≥50% but <quorum**: New validators inherit vote state, continue

---

## 6. Slashing Conditions

### 6.1 Slashable Offenses

Validators stake is at risk for misbehavior:

| Offense | Severity | Slash Amount | Detection Method |
|---------|----------|--------------|------------------|
| **Double-voting** | CRITICAL | 100% stake | Cryptographic proof (two signed votes for same round) |
| **Equivocation** | CRITICAL | 100% stake | Conflicting signed statements |
| **Collusion** (proven) | CRITICAL | 100% stake | On-chain evidence of coordination |
| **Unavailability** (persistent) | HIGH | 50% stake | Missing >30% of rounds in epoch |
| **Censorship** (proven) | HIGH | 50% stake | Systematic exclusion of valid beliefs |
| **Invalid vote** | MEDIUM | 20% stake | Voting to elevate belief that fails verification |
| **Late voting** | LOW | 5% stake | Consistently voting after deadline |

### 6.2 Slashing Protocol

```typescript
SlashingEvent {
  id: UUID
  validator: DID
  offense: SlashingOffense
  
  // Evidence
  evidence: SlashingEvidence
  evidence_hash: bytes32
  
  // Amounts
  stake_at_risk: float
  slash_amount: float
  
  // Process
  reported_by: DID
  reported_at: timestamp
  status: SlashingStatus           // PENDING | CONFIRMED | APPEALED | EXECUTED | REJECTED
  
  // Resolution
  resolution_votes: Map<DID, boolean>  // Other validators vote
  resolution_at?: timestamp
  appeal_deadline?: timestamp
}

// Slashing requires validator consensus
function resolveSlashing(event: SlashingEvent, validators: Validator[]): SlashingOutcome {
  // Exclude accused from voting
  const voters = validators.filter(v => v.agent_id !== event.validator)
  
  // For CRITICAL offenses with cryptographic proof: automatic
  if (event.offense.severity === 'CRITICAL' && event.evidence.cryptographic_proof) {
    return { slash: true, amount: event.stake_at_risk }
  }
  
  // Otherwise: 2/3 of other validators must agree
  const confirmVotes = Object.values(event.resolution_votes).filter(v => v).length
  const threshold = Math.ceil(voters.length * 2 / 3)
  
  if (confirmVotes >= threshold) {
    return { slash: true, amount: event.slash_amount }
  } else {
    return { slash: false }
  }
}
```

### 6.3 Slashing Distribution

Slashed stake is distributed:
- 30% → Reporter (incentivize reporting)
- 20% → Consensus security fund (pays for audits, bug bounties)
- 50% → Burned (reduces total reputation supply)

---

## 7. Consensus Protocol Integration

### 7.1 Elevation Voting

When a belief is proposed for L4 elevation:

```typescript
ElevationProposal {
  id: UUID
  belief_id: UUID
  proposed_at: timestamp
  
  // Proposer (can be any agent, not just validator)
  proposer: DID
  proposer_stake: float              // Stake at risk if frivolous
  
  // Voting
  voting_epoch: uint64
  voting_deadline: timestamp
  
  votes: Map<DID, ElevationVote>
  
  // Requirements (from Consensus SPEC)
  requirements_checked: {
    independent_domains: boolean
    independence_score: boolean
    minimum_age: boolean
    verification_count: boolean
    active_challenges: boolean
  }
  
  // Outcome
  outcome?: 'ELEVATED' | 'REJECTED' | 'DEFERRED'
  finalized_at?: timestamp
}

ElevationVote {
  validator: DID
  vote: 'APPROVE' | 'REJECT' | 'ABSTAIN'
  
  // Each validator independently verifies
  verification_report: {
    independence_verified: boolean
    evidence_chains_traced: boolean
    requirements_met: boolean
    concerns: string[]
  }
  
  // Cryptographic
  signature: Signature
  timestamp: timestamp
}
```

### 7.2 Voting Process

```
Belief proposed for L4 elevation
  │
  ├── Proposal broadcast to active validators
  │
  ├── Each validator (independently):
  │   ├── Trace evidence chains to original sources
  │   ├── Verify independence score calculation
  │   ├── Check all elevation requirements
  │   ├── Review for manipulation indicators
  │   └── Cast signed vote with verification report
  │
  ├── Voting period: 48 hours (or until quorum)
  │
  ├── Vote tallying:
  │   ├── APPROVE votes ≥ 2f+1 → ELEVATED
  │   ├── REJECT votes ≥ 2f+1 → REJECTED
  │   └── Neither → DEFERRED (re-vote next epoch)
  │
  └── If ELEVATED:
      ├── Create CommunalKnowledge record
      ├── Store validator signatures as independence certificate
      └── Emit ElevatedToCommunal event
```

---

## 8. Security Analysis

### 8.1 Threat Mitigations

| Threat (from THREAT-MODEL.md) | Mitigation |
|-------------------------------|------------|
| **Consensus Node Capture** | VRF selection + stake + diversity constraints |
| **Sybil attack on selection** | Identity attestation requirements + 180-day age + reputation threshold |
| **Collusion** | Federation diversity limits + stake at risk + slashing |
| **Long-term entrenchment** | Tenure penalty + mandatory 20% new validators |
| **Stake centralization** | Tier caps + diversity requirements |
| **Bribery** | High stakes + slashing + reputation risk |

### 8.2 Attack Cost Analysis

**To capture consensus (control 2f+1 of 3f+1 validators):**

Assuming n=31 (f=10), attacker needs 21 validators:

1. **Reputation cost**: 21 × 0.10 (min stake) = 2.1 reputation
   - But reputation requires legitimate network participation over time
   - At max 0.1/day, minimum 21 × 180 days = 3,780 agent-days of activity

2. **Identity attestation**: Each needs attestation
   - Social: requires 3 existing validators to vouch (circular dependency)
   - External: requires 21 real identities with verifiable credentials

3. **Selection probability**: Even with eligibility, selection is probabilistic
   - Must maintain stakes across multiple epochs
   - Diversity constraints prevent single-federation capture

4. **Detection risk**: Coordinated behavior triggers analysis
   - Similar voting patterns
   - Federation membership overlap
   - Temporal coordination in stakes

**Cost estimate**: Capturing consensus requires years of preparation and real-world identity verification, making it comparable to 51% attacks on major PoS chains.

---

## 9. Governance & Parameters

### 9.1 Adjustable Parameters

These parameters can be adjusted through network governance:

| Parameter | Default | Range | Governance Threshold |
|-----------|---------|-------|---------------------|
| `min_reputation` | 0.5 | 0.3-0.7 | 75% validator approval |
| `min_account_age_days` | 180 | 90-365 | 75% validator approval |
| `min_stake` | 0.10 | 0.05-0.20 | 75% validator approval |
| `epoch_duration_days` | 7 | 3-14 | 90% validator approval |
| `max_federation_percent` | 20% | 10%-33% | 75% validator approval |
| `max_tenure_epochs` | ∞ | 4-∞ | 66% validator approval |

### 9.2 Emergency Procedures

In case of detected attacks or critical bugs:

1. **Emergency pause**: 90% of validators can pause elevations
2. **Emergency parameter change**: 90% can adjust parameters without delay
3. **Validator removal**: 95% can remove a validator mid-epoch (for proven attacks)

---

## 10. Implementation Notes

### 10.1 VRF Implementation

Use **ECVRF-EDWARDS25519-SHA512-TAI** (RFC 9381) for VRF operations:
- Same curve as identity keys (Ed25519)
- Well-analyzed security properties
- Efficient verification

### 10.2 Epoch Seed Bootstrap

For the first epoch (network genesis):
- Use hash of genesis block + founding federation signatures
- Require founding validators to be explicitly listed in genesis config
- First 3 epochs use reduced security (lower thresholds) during bootstrap

### 10.3 Monitoring

Node operators should monitor:
- Selection fairness (chi-squared test on validator distribution)
- Voting correlation (detect collusion patterns)
- Availability rates
- Evidence chain verification times

---

## 11. Appendix: Selection Weight Examples

### Example 1: New Standard Validator
- Tier: Standard (1.0×)
- Reputation: 0.55 → factor: 1.025
- Attestations: 1 → factor: 1.1
- Tenure: 0 epochs → factor: 1.0
- Performance: N/A → factor: 1.0
- **Total weight: 1.13**

### Example 2: Experienced Guardian
- Tier: Guardian (2.0×)
- Reputation: 0.85 → factor: 1.175
- Attestations: 3 → factor: 1.3
- Tenure: 6 epochs → factor: 0.81 (penalty kicks in)
- Performance: 98% → factor: 1.096
- **Total weight: 2.71**

### Example 3: Long-tenured Validator (Entrenchment Penalty)
- Tier: Enhanced (1.5×)
- Reputation: 0.70 → factor: 1.10
- Attestations: 2 → factor: 1.2
- Tenure: 12 epochs → factor: 0.43 (heavy penalty: 0.9^8)
- Performance: 95% → factor: 1.09
- **Total weight: 0.93** (lower than new Standard validator!)

---

*"Decentralized consensus requires decentralized selection. The moment selection centralizes, truth centralizes."*
