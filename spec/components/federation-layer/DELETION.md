# Deletion Protocol

## Overview

Federated systems face a fundamental tension: data propagates to sovereign nodes that cannot be compelled to delete. This protocol provides **cryptographic deletion** — making content unreadable rather than ensuring byte-level erasure.

## Principles

1. **Encryption-first**: All federated content is encrypted before sharing
2. **Key-controlled access**: Deletion = key revocation
3. **Tombstone propagation**: Deletion requests spread like content
4. **Reputation enforcement**: Nodes ignoring tombstones lose trust
5. **Best-effort honesty**: We document limitations, don't overpromise

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    BELIEF ENCRYPTION                            │
│                                                                 │
│  plaintext_belief ──► AES-256-GCM(belief_key) ──► ciphertext   │
│                                                                 │
│  belief_key ──► encrypt_for_recipients(pub_keys) ──► key_blob  │
│                                                                 │
│  federated_belief = { ciphertext, key_blob, metadata }         │
└─────────────────────────────────────────────────────────────────┘
```

### Key Hierarchy

```
node_identity_key (ed25519)
    │
    └── federation_encryption_key (x25519, derived)
            │
            └── belief_key (AES-256, per-belief or per-batch)
```

## Deletion Flow

### 1. Originator Requests Deletion

```typescript
interface DeletionRequest {
  belief_id: UUID;
  tombstone_id: UUID;
  reason: 'user_request' | 'legal_requirement' | 'accidental_share' | 'other';
  originator_id: NodeIdentity;
  signature: Ed25519Signature;  // Proves originator authorized deletion
  timestamp: ISO8601;
  propagate: boolean;  // Should peers forward this?
  legal_reference?: string;  // For compliance documentation
}
```

### 2. Tombstone Creation

```typescript
interface Tombstone {
  id: UUID;
  belief_id: UUID;
  deletion_request: DeletionRequest;
  key_revocation: {
    revoked_key_hash: SHA256;  // Hash of the belief_key being revoked
    revocation_timestamp: ISO8601;
  };
  created_at: ISO8601;
}
```

### 3. Propagation

```
Originator ──► Tombstone ──► Peer 1 ──► Peer 1's peers
                         ──► Peer 2 ──► Peer 2's peers
                         ──► Peer N ──► ...
```

Tombstones propagate through the same channels as beliefs, with the same trust relationships.

### 4. Receiving Node Actions

On receiving a tombstone, a compliant node MUST:

1. **Verify signature** — Confirm originator authorized deletion
2. **Revoke key locally** — Mark belief_key as revoked in local keystore
3. **Mark belief as deleted** — Set `deleted_at`, keep tombstone
4. **Optionally purge ciphertext** — Can delete encrypted content (optional)
5. **Forward tombstone** — If `propagate: true`, send to own peers
6. **Log for audit** — Record deletion for compliance

### 5. Query Behavior Post-Deletion

```typescript
// Deleted beliefs return tombstone, not content
query_belief(deleted_id) → {
  status: 'deleted',
  tombstone: Tombstone,
  content: null
}
```

## Cryptographic Deletion Guarantees

### What This Achieves

| Guarantee | Status |
|-----------|--------|
| Content unreadable without key | ✅ Achieved |
| Originator can revoke access | ✅ Achieved |
| Deletion propagates to honest peers | ✅ Achieved |
| Audit trail of deletion | ✅ Achieved |
| Malicious nodes can't read after revocation | ✅ Achieved (if they didn't cache plaintext) |

### What This Does NOT Achieve

| Non-guarantee | Reality |
|---------------|---------|
| Byte-level erasure on all nodes | ❌ Cannot force sovereign nodes |
| Deletion from backups | ❌ Nodes control their own backups |
| Deletion if plaintext was cached | ❌ If node decrypted and stored, they have it |
| Deletion from node's memory | ❌ Transient exposure possible |

### Honest Documentation

We document these limitations publicly. Users understand:

> "When you delete a federated belief, we revoke the encryption key and propagate a deletion request. Compliant nodes will be unable to read the content. However, we cannot guarantee deletion from non-compliant nodes, backups, or nodes that cached the plaintext before deletion."

## Grace Period (Accidental Sharing)

For accidental shares, a grace period provides additional protection:

```typescript
interface FederationConfig {
  // Delay before belief actually propagates to peers
  propagation_delay_seconds: number;  // Default: 300 (5 minutes)
  
  // During this window, deletion is "free" — content never left origin
  grace_period_seconds: number;  // Default: 300 (5 minutes)
}
```

**During grace period:**
- Belief marked as `pending_federation`
- Not yet sent to any peer
- Deletion is instant and complete
- No tombstone needed

**After grace period:**
- Normal deletion protocol applies
- Tombstone propagation required

## Legal Compliance

### GDPR Article 17 (Right to Erasure)

Our position: Cryptographic deletion satisfies "erasure" because:
1. Personal data becomes unreadable
2. We take reasonable technical measures
3. We propagate deletion requests to processors (peers)
4. We document the process

### Legal Hold

For legal proceedings, nodes can:
1. Preserve tombstone (proves deletion was requested)
2. Preserve encrypted content (unreadable without key)
3. Not revoke key if legally required to preserve

```typescript
interface LegalHold {
  belief_ids: UUID[];
  hold_reason: string;
  authority: string;
  expires_at?: ISO8601;
}
```

### Jurisdictional Differences

Federation agreements specify which jurisdiction's laws apply:
- EU nodes: GDPR applies
- US nodes: Sector-specific laws
- Mixed: Most restrictive interpretation

## Trust Implications

### Non-Compliance Detection

If Node A sends a tombstone and later observes Node B still serving the content:

```typescript
// Node B violated deletion protocol
report_non_compliance(node_b, {
  type: 'tombstone_violation',
  tombstone_id: uuid,
  evidence: {
    our_tombstone: Tombstone,
    their_response: BeliefContent,  // They returned content after deletion
    timestamp: ISO8601
  }
});
```

### Reputation Impact

```typescript
// Tombstone violation is severe
trust_penalties = {
  tombstone_ignored: -0.5,  // Major trust reduction
  repeated_violation: -1.0  // Effectively untrusted
}
```

Nodes that consistently ignore tombstones will be isolated from the federation through natural trust decay.

## Implementation Notes

### Key Storage

```sql
CREATE TABLE belief_keys (
  belief_id UUID PRIMARY KEY,
  encrypted_key BYTEA NOT NULL,  -- Encrypted with node's master key
  key_hash CHAR(64) NOT NULL,    -- For revocation matching
  created_at TIMESTAMPTZ NOT NULL,
  revoked_at TIMESTAMPTZ,        -- NULL if not revoked
  revocation_tombstone_id UUID REFERENCES tombstones(id)
);

CREATE INDEX idx_belief_keys_hash ON belief_keys(key_hash);
CREATE INDEX idx_belief_keys_revoked ON belief_keys(revoked_at) WHERE revoked_at IS NOT NULL;
```

### Tombstone Storage

```sql
CREATE TABLE tombstones (
  id UUID PRIMARY KEY,
  belief_id UUID NOT NULL,
  reason TEXT NOT NULL,
  originator_id UUID NOT NULL,
  signature BYTEA NOT NULL,
  legal_reference TEXT,
  received_at TIMESTAMPTZ NOT NULL,
  propagated_at TIMESTAMPTZ,
  
  CONSTRAINT valid_reason CHECK (reason IN ('user_request', 'legal_requirement', 'accidental_share', 'other'))
);

CREATE INDEX idx_tombstones_belief ON tombstones(belief_id);
```

## API Endpoints

```typescript
// Request deletion of own belief
POST /federation/delete
Body: DeletionRequest
Response: { tombstone_id, propagation_status }

// Receive tombstone from peer
POST /federation/tombstone
Body: Tombstone
Response: { accepted: boolean, reason?: string }

// Check if belief is deleted
GET /federation/belief/{id}/status
Response: { exists: boolean, deleted: boolean, tombstone?: Tombstone }
```

## Summary

This protocol provides:

1. **Meaningful deletion** — Content becomes cryptographically inaccessible
2. **Propagation** — Deletion requests spread through the network
3. **Enforcement** — Non-compliant nodes lose reputation
4. **Honesty** — We document what we can and can't guarantee
5. **Legal defensibility** — Reasonable measures, documented process

It does not provide:

1. **Absolute erasure** — Impossible in federated systems
2. **Control over malicious nodes** — They're sovereign
3. **Protection against cached plaintext** — If they saved it, they have it

This is the honest middle ground between "deletion is impossible" and "deletion is guaranteed."
