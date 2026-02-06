# Valence Governance

How Valence is governed today, and how that will change as the network grows. This is a transition plan, not a constitution — it will be revised as we learn.

## Guiding Principle

Governance should be as decentralized as the network can sustain. Premature decentralization produces chaos; permanent centralization produces capture. The goal is to move authority outward as the community develops the capacity to hold it.

---

## Phase 1: BDFL (Now)

**Condition:** Early development, small contributor base, rapid iteration needed.

The Valence org (Orobobos) acts as benevolent dictator. This is honest about where we are: a small team making fast decisions.

**What this means:**
- Core team makes architectural and protocol decisions
- Community input is welcomed but not binding
- Roadmap is set by the core team
- Principles (see `PRINCIPLES.md`) constrain all decisions, including the core team's

**Accountability:**
- All decisions documented in public (GitHub issues, ADRs, this repo)
- Principles are already binding — not aspirational
- The core team can be challenged on principle violations by anyone

**Exit criteria → Phase 2:**
- 5+ sustained external contributors (code, not just issues)
- Stable protocol specification (post-v1.0)
- At least one independent node operator

## Phase 2: Shared Stewardship

**Condition:** Growing contributor base, stable core protocol, multiple stakeholders.

Authority expands from core team to include sustained contributors. Think Apache-style meritocratic governance.

**What this means:**
- Contributor council with commit/merge authority over their domains
- Protocol changes require council review (not just core team approval)
- Core team retains veto on principle violations only
- Formal ADR (Architecture Decision Record) process for significant changes

**Roles:**
- **Core maintainers** — original team, shrinking authority over time
- **Domain stewards** — earned through sustained contribution to specific areas
- **Community members** — voice in discussions, proposal rights

**Decision process:**
- Routine changes: maintainer approval
- Significant changes: ADR + council review
- Principle-affecting changes: broad community input + supermajority

**Exit criteria → Phase 3:**
- Multiple independent implementations or deployments
- Governance disputes successfully resolved through process (not fiat)
- Community demonstrates capacity for self-governance

## Phase 3: Network Governance

**Condition:** Mature network, multiple independent operators, the system is bigger than any one org.

Governance follows the IETF model: rough consensus and running code. The Valence org becomes one participant among many.

**What this means:**
- Protocol changes through open RFC process
- Rough consensus — not unanimity, not majority vote
- Running code matters — proposals backed by working implementations carry more weight
- No single entity has veto power (including the original team)
- Governance of the protocol is separate from governance of individual nodes

**Dispute resolution:**
- Technical disputes: resolved by evidence and running code
- Governance disputes: escalation process with rotating mediators
- Principle violations: community enforcement through trust network (not central authority)

---

## Network Model: One Network, Trust-Gated Visibility

Valence is one network, not a federation of isolated instances. But visibility within that network is controlled by trust relationships.

### Why One Network

Fragmentation defeats the purpose. If beliefs only propagate within isolated clusters, you get echo chambers with extra steps. A single network with permeable boundaries keeps the knowledge substrate connected.

### How Trust Gates Work

- **Public commons** — Beliefs explicitly shared publicly are visible to all network participants. This is the shared substrate: the baseline of common knowledge.
- **Trust circles** — Beliefs shared within trust relationships are visible only to those relationships. Trust is directional (I can trust you without you trusting me) and domain-specific (I trust your technical judgment, not your music taste).
- **Node operators** set their own policies for what they host and relay, but cannot see encrypted private beliefs.

### What This Avoids

- **Walled gardens** — No instance admin decides what their users can see from outside
- **Forced openness** — You're not choosing between "public" and "nothing"
- **Balkanization** — The network doesn't split along political/social lines into non-communicating shards

### What This Requires

- End-to-end encryption for private beliefs
- A trust protocol that works across node boundaries
- Careful design of the public commons (spam resistance, quality signals)

---

## Open Questions

Things we haven't figured out yet. Documenting them honestly is better than pretending we have answers.

1. **How are governance transitions triggered?** The exit criteria above are qualitative, not quantitative. How do we avoid either premature transition or clinging to authority?
2. **Economic sustainability.** Who pays for infrastructure? How do node operators sustain themselves without creating perverse incentives?
3. **Legal entity structure.** What legal form supports Phase 3 governance? Foundation? Cooperative? Something new?
4. **Sybil resistance in governance.** How do we prevent governance capture through fake identities, especially in Phase 3?

---

## Amendments

This document will change. When it does:

- Changes go through the process appropriate to the current phase
- Rationale is documented
- Previous versions remain in git history
- Principle violations require the extraordinary justification described in `PRINCIPLES.md`
