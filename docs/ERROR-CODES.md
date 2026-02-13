# Error Codes

All error codes used across the Valence API. Defined in `src/valence/server/errors.py`.

## REST API Error Response Format

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description"
  }
}
```

## Error Codes by Category

### Validation Errors (HTTP 400)

| Code | Description | Helper |
|------|-------------|--------|
| `VALIDATION_MISSING_FIELD` | Required field not provided | `missing_field_error(field)` |
| `VALIDATION_INVALID_FORMAT` | Field has wrong format (e.g., invalid UUID) | `invalid_format_error(field, details)` |
| `VALIDATION_INVALID_VALUE` | Field value is invalid | `validation_error(message)` |
| `VALIDATION_INVALID_JSON` | Request body is not valid JSON | `invalid_json_error()` |

### Authentication Errors (HTTP 401)

| Code | Description | Helper |
|------|-------------|--------|
| `AUTH_INVALID_TOKEN` | Bearer token is invalid or expired | `auth_error(message)` |
| `AUTH_MISSING_TOKEN` | No authentication token provided | `auth_error(message, AUTH_MISSING_TOKEN)` |
| `AUTH_SIGNATURE_FAILED` | Ed25519 signature verification failed | `auth_error(message, AUTH_SIGNATURE_FAILED)` |
| `AUTH_FEDERATION_REQUIRED` | Federation auth required for this endpoint | `auth_error(message, AUTH_FEDERATION_REQUIRED)` |

### Authorization Errors (HTTP 403)

| Code | Description | Helper |
|------|-------------|--------|
| `FORBIDDEN_NOT_OWNER` | User is not the resource owner | `forbidden_error(message, FORBIDDEN_NOT_OWNER)` |
| `FORBIDDEN_INSUFFICIENT_PERMISSION` | User lacks required permissions | `forbidden_error(message)` |

### Not Found Errors (HTTP 404)

| Code | Description | Helper |
|------|-------------|--------|
| `NOT_FOUND_RESOURCE` | Generic resource not found | `not_found_error(resource)` |
| `NOT_FOUND_BELIEF` | Belief not found | `not_found_error(resource, NOT_FOUND_BELIEF)` |
| `NOT_FOUND_USER` | User not found | `not_found_error(resource, NOT_FOUND_USER)` |
| `NOT_FOUND_SHARE` | Share not found | `not_found_error(resource, NOT_FOUND_SHARE)` |
| `NOT_FOUND_NOTIFICATION` | Notification not found | `not_found_error(resource, NOT_FOUND_NOTIFICATION)` |
| `NOT_FOUND_TOMBSTONE` | Tombstone record not found | `not_found_error(resource, NOT_FOUND_TOMBSTONE)` |
| `NOT_FOUND_NODE` | Federation node not found | `not_found_error(resource, NOT_FOUND_NODE)` |
| `FEATURE_NOT_ENABLED` | Feature is disabled | `feature_not_enabled_error(feature)` |

### Conflict Errors (HTTP 409)

| Code | Description | Helper |
|------|-------------|--------|
| `CONFLICT_ALREADY_EXISTS` | Resource already exists | `conflict_error(message)` |
| `CONFLICT_ALREADY_REVOKED` | Resource already revoked | `conflict_error(message, CONFLICT_ALREADY_REVOKED)` |

### Rate Limiting (HTTP 429)

| Code | Description | Helper |
|------|-------------|--------|
| `RATE_LIMITED` | Too many requests | See [RATE-LIMITS.md](RATE-LIMITS.md) |

### Server Errors (HTTP 500)

| Code | Description | Helper |
|------|-------------|--------|
| `INTERNAL_ERROR` | Internal server error | `internal_error(message)` |

### Service Errors (HTTP 503)

| Code | Description | Helper |
|------|-------------|--------|
| `SERVICE_UNAVAILABLE` | Required service not initialized | `service_unavailable_error(service)` |

## MCP JSON-RPC Error Codes

MCP tools use JSON-RPC 2.0 error codes:

| Code | Meaning |
|------|---------|
| `-32700` | Parse error |
| `-32600` | Invalid request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error |
| `-32001` | Unauthorized (custom) |
| `-32002` | Rate limited (custom) |

## OAuth 2.1 Error Codes

OAuth endpoints use RFC 6749 error codes:

| Code | Description | HTTP Status |
|------|-------------|-------------|
| `invalid_request` | Malformed or missing required parameters | 400 |
| `invalid_client` | Client authentication failed | 401 |
| `invalid_grant` | Authorization code or refresh token invalid/expired | 400 |
| `unauthorized_client` | Client not authorized for this flow | 403 |
| `unsupported_grant_type` | Grant type not supported | 400 |
| `invalid_scope` | Requested scope is invalid | 400 |
| `unsupported_response_type` | Response type not supported | 400 |
| `invalid_redirect_uri` | Redirect URI doesn't match registration | 400 |

OAuth error response format:
```json
{
  "error": "invalid_request",
  "error_description": "Human-readable description"
}
```

## MCP Tool Error Format

MCP tool handlers return success/failure in the response body:

```json
{
  "success": false,
  "error": "Belief not found"
}
```

This is distinct from JSON-RPC errors (which indicate protocol-level failures).
