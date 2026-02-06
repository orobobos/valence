# Valence Security Audit Report

**Date:** 2026-02-05
**Auditor:** OpenClaw Security Subagent
**Repository:** orobobos/valence
**Commit:** bd1c4e2 (as of audit date)
**Scope:** Authentication, Authorization, Input Validation, Cryptography, Secrets Management, Dependencies

---

## Executive Summary

This security audit examined the Valence personal knowledge substrate codebase, following up on the 2026-02-04 audit. The critical XSS vulnerability from the previous audit has been fixed. Overall security posture has improved. One high-severity dependency issue remains, and several medium/low items from the previous audit are still open but documented as acceptable for single-instance deployments.

| Severity | Count | Change from 2026-02-04 |
|----------|-------|------------------------|
| **Critical** | 0 | ↓1 (fixed) |
| **High** | 0 | ↓2 (Matrix bot removed, PyJWT false positive) |
| **Medium** | 4 | ↓1 |
| **Low** | 4 | — |

---

## Previous Audit Status

### CRITICAL-001: XSS in OAuth Login Page — ✅ FIXED

**File:** `src/valence/server/oauth.py`
**Status:** Resolved

The OAuth login page now properly escapes user-controlled values using `html.escape()`:

```python
# Line 436-440 (fixed implementation)
def _login_page(params: dict[str, Any], client_name: str, error: str | None = None) -> str:
    # Escape user-controlled values to prevent XSS
    safe_client_name = html.escape(client_name)
    error_html = ""
    if error:
        safe_error = html.escape(error)
        error_html = f'<div class="error">{safe_error}</div>'
```

The `_error_page()` function also now escapes messages properly.

**Verification:** Code review confirms html.escape() is applied to all user-controlled values before HTML interpolation.

---

### HIGH-002: Matrix Bot Command Injection — ✅ N/A (Removed)

**Status:** Not applicable

The Matrix bot (`src/valence/agents/matrix_bot.py`) referenced in the previous audit does not exist in the current codebase. No subprocess calls with user input were found in `src/`.

---

## Open Issues

### HIGH-001: PyJWT Dependency Version Mismatch — ✅ FALSE POSITIVE

**File:** `pyproject.toml`
**Severity:** ~~High~~ None

**Description:**
The audit reported `PyJWT 2.7.0` installed when `pyproject.toml` specifies `>=2.11.0`.

**Root Cause:** Audit ran in a stale virtual environment that hadn't been updated.

**Verification:**
```bash
# Fresh venv confirms correct version
$ python -m venv .fresh-venv && source .fresh-venv/bin/activate
$ pip install -e ".[dev]"
$ pip show PyJWT | grep Version
Version: 2.11.0  # ✅ Correct
```

**Lesson Learned:** Audit sub-agents must create fresh venvs before checking dependency versions. See `docs/SUBAGENT-WORKFLOW.md` for updated audit procedure.

**Status:** Closed (false positive)

---

### MED-001: Missing CSRF Protection on OAuth Authorize POST

**File:** `src/valence/server/oauth.py`
**Severity:** Medium
**Status:** Open (from 2026-02-04 audit)

The OAuth authorization form relies on OAuth's `state` parameter but doesn't include a dedicated CSRF token. While the state parameter provides some protection, a dedicated CSRF token would be more robust.

**Recommendation:** Add a CSRF token to the login form and validate on POST.

---

### MED-002: In-Memory Token Stores Without Persistence

**File:** `src/valence/server/oauth_models.py`
**Severity:** Medium
**Status:** Open - Acceptable for single-instance deployments

Authorization codes and refresh tokens are stored in-memory dictionaries. This means tokens are lost on restart and doesn't support horizontal scaling.

**Documentation:** This limitation should be documented in deployment guides.

---

### MED-003: In-Memory Rate Limiting

**File:** `src/valence/server/rate_limit.py`, `src/valence/server/app.py`
**Severity:** Medium
**Status:** Open - Acceptable for single-instance deployments

Rate limiting uses in-memory dictionaries and won't work across multiple instances.

**Documentation:** This limitation should be documented for multi-instance deployments.

---

### MED-004: Permissive Default CORS Configuration

**File:** `src/valence/server/config.py`
**Severity:** Medium
**Status:** Open

Default CORS allows all origins (`["*"]`). This is acceptable for development but should be restricted in production.

```python
allowed_origins: list[str] = Field(
    default=["*"],
    description="Allowed CORS origins",
)
```

**Documentation:** Production deployment guides should specify CORS configuration.

---

### LOW-001: Missing Security Headers

**File:** `src/valence/server/app.py`
**Severity:** Low
**Status:** Open (from 2026-02-04 audit)

HTML responses don't include security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `Strict-Transport-Security`).

---

### LOW-002: JWT Secret Auto-Generation in Development

**File:** `src/valence/server/config.py`
**Severity:** Low
**Status:** Open - Working as designed

JWT secrets are auto-generated in non-production mode. The production validator properly enforces explicit configuration:

```python
if is_production and self.oauth_enabled:
    if not self.oauth_jwt_secret:
        raise ValueError(
            "VALENCE_OAUTH_JWT_SECRET is required in production..."
        )
    if len(self.oauth_jwt_secret) < 32:
        raise ValueError(
            "VALENCE_OAUTH_JWT_SECRET must be at least 32 characters..."
        )
```

---

### LOW-003: OAuth Password in Environment Variable

**File:** `src/valence/server/config.py`
**Severity:** Low
**Status:** Open - Common pattern

OAuth password is configured via environment variable. This is standard practice; consider file-based secrets support for enhanced security.

---

### LOW-004: Some Endpoints Lack Input Bounds

**Files:** Various federation endpoints
**Severity:** Low
**Status:** Open

Some endpoints accept `limit` parameters without upper bound validation. The database queries are parameterized and safe, but unbounded limits could cause performance issues.

---

## Security Strengths Confirmed

### SQL Injection Prevention ✅

All database queries use parameterized statements with `%s` placeholders. The `count_rows()` function uses a frozen allowlist:

```python
# src/valence/core/db.py
VALID_TABLES = frozenset([
    "beliefs", "sessions", "patterns", "conversations",
    "federation_nodes", "node_trust", "sync_state", ...
])

def count_rows(table_name: str) -> int:
    if table_name not in VALID_TABLES:
        raise ValueError(f"Table not in allowlist: {table_name}...")
```

### Cryptographic Implementation ✅

**Ed25519/X25519 (network/crypto.py):**
- Uses `cryptography` library's Ed25519 and X25519 primitives
- HKDF key derivation with domain separator (`valence-relay-v1`)
- AES-256-GCM for content encryption
- Ephemeral keys per message for forward secrecy

**VRF (consensus/vrf.py):**
- Domain separators prevent cross-protocol attacks:
  ```python
  DOMAIN_SEPARATOR_VRF_PROVE = b"valence-vrf-prove-v1"
  DOMAIN_SEPARATOR_VRF_HASH = b"valence-vrf-hash-v1"
  DOMAIN_SEPARATOR_EPOCH_SEED = b"valence-epoch-seed-v1"
  ```
- Thorough security documentation in module docstring
- Deterministic output from Ed25519 signatures

### Secure Token Handling ✅

```python
# Token generation using secrets module
raw_token = secrets.token_urlsafe(32)

# Token storage as SHA-256 hash
token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

# PKCE verification with constant-time comparison
return secrets.compare_digest(computed_challenge, code_challenge)

# Credential validation with timing-safe comparison
secrets.compare_digest(username, settings.oauth_username or "")
```

### File Permissions ✅

Sensitive files are created with restrictive permissions:
```python
self.token_file.chmod(0o600)
self.clients_file.chmod(0o600)
```

### PII Protection ✅

The `compliance/pii_scanner.py` module prevents sensitive data federation:
- Pattern matching for emails, phone numbers, SSNs, credit cards
- Classification levels (L0-L4) with federation rules
- Hard blocks for L4 (prohibited) content
- Soft blocks for L3 (personal) requiring explicit confirmation

### DID Signature Verification ✅

Federation endpoints use DID signature verification with replay protection:
```python
# Timestamp freshness check (5-minute window)
if abs(now - timestamp) > 300:
    return None

# Message includes: method + path + timestamp + nonce + body_hash
message = f"{request.method} {request.url.path} {timestamp} {nonce} {body_hash}"
```

### Anti-Gaming Measures ✅

The `consensus/anti_gaming.py` module implements:
- Tenure penalties to prevent validator entrenchment
- Diversity scoring (Gini coefficient, entropy)
- Collusion detection (voting correlation, stake timing, federation clustering)
- Slashing evidence generation for high-severity alerts

### No Dangerous Patterns ✅

- No `subprocess` calls with `shell=True` in src/
- No `eval()` calls on user input
- No string formatting in SQL queries

---

## Recommendations Summary

### Immediate
~~1. **HIGH-001**: Update PyJWT to match pyproject.toml specification (>=2.11.0)~~ — FALSE POSITIVE, closed

### Short Term (30 days)
2. Add CSRF tokens to OAuth form
3. Add security headers middleware
4. Document single-instance limitations for rate limiting and token stores
5. Document CORS configuration requirements for production

### Medium Term (90 days)
6. Consider Redis-backed rate limiting for multi-instance deployments
7. Consider database-backed token storage for horizontal scaling
8. Add input bounds validation on all `limit` parameters
9. Implement file-based secrets support as alternative to environment variables

---

## Conclusion

The Valence codebase demonstrates strong security practices. The critical XSS vulnerability from the previous audit has been properly remediated with HTML escaping. The PyJWT version issue was a false positive caused by a stale audit environment.

The overall security posture is **suitable for production**. No critical or high-severity issues remain. The documented limitations around in-memory storage are acceptable for single-instance deployments.

---

*This audit was conducted as a point-in-time review. Regular security audits are recommended as the codebase evolves.*
