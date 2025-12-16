# System Outline

*The shape of the system. Architecture derived from principles.*

---

## Topology

```
┌─────────────────────────────────────────────────────────────────┐
│                         INSTITUTIONS                            │
│              (governments, corporations, markets)               │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ collective signal
                              │ (privacy-preserving aggregation)
┌─────────────────────────────────────────────────────────────────┐
│                      AGGREGATION LAYER                          │
│         values + preferences + commitments = leverage           │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ federated, user-controlled
                              │
┌─────────────────────────────────────────────────────────────────┐
│                       AGENT LAYER                               │
│              your agent ←→ knowledge base (yours)               │
│                    learns you, represents you                   │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ all interaction flows through agent
                              │
┌─────────────────────────────────────────────────────────────────┐
│                          HUMAN                                  │
│                  (never touches system directly)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ agent mediates all services
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     SERVICE PROVIDERS                           │
│          (interchangeable commodities underneath)               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### The Agent
- Represents the user exclusively
- Learns from user-owned knowledge base
- Mediates all interactions with services and the platform
- The agent's alignment is to its user, verified and auditable

### The Knowledge Base
- User-owned, user-controlled
- Contains the data that lets the agent know you
- Never leaves user control unencrypted
- The source of values, preferences, and context that make aggregation meaningful

### The Aggregation Layer
- Privacy-preserving: no individual exposed
- Federated: computation happens at the edges
- Verifiable: aggregates are real commitments, not surveys
- Purpose-constrained: only exists to increase value for users

### The Institutional Interface
- Aggregated signal creates negotiating leverage
- Users don't negotiate individually—the collective speaks
- Enables influence on markets, policy, corporate behavior

---

## Development Model

```
Human Intent → Agent Mediation → AI Implementation → Principle Constraints
```

- **Humans express intent** through interaction with their agent
- **Agents translate** intent into actionable requests
- **AI implements** changes (Claude or equivalent, bound by constitution)
- **Principles constrain** what implementations are valid
- **Code is suggestion** until AI accepts it in accordance with principles

### Self-Governance
- Evolution driven by user consensus, not central authority
- Changes propagate through the same agent-mediated channel
- The system's development is subject to its own principles

---

## Trust Architecture

The trust chain is local, not institutional:

1. **User trusts their agent** (because it's theirs, auditable, aligned to them)
2. **Agent trusts AI-as-implementer** (because AI is bound by constitution)
3. **Constitution is enforced by structure** (not promises)

Users don't need to trust "the platform." They trust their agent. The rest is architecture.

---

## Key Properties

| Property | Derived From |
|----------|--------------|
| Agent can't be turned against user | Structural Integrity |
| Aggregation can't extract value from users | Collective Emergence |
| System survives being copied | Openness as Resilience |
| Evolution requires user consensus | Mission Permanence |
| Every decision traceable to principles | Principles as Foundation |

---

*This outline describes shape, not implementation. Implementations will vary and evolve. The shape is constrained by principles.*
