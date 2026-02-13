# Rate Limits

Rate limiting configuration and behavior for the Valence HTTP server.

## Configuration

| Setting | Default | Env Var | Description |
|---------|---------|---------|-------------|
| `rate_limit_rpm` | 60 | `VALENCE_RATE_LIMIT_RPM` | Requests per minute per client |

## How It Works

Rate limiting is **in-memory, per-instance** using a sliding window. State resets on server restart.

### Scope

Limits are applied per unique key:
- **MCP endpoints:** Per Bearer token / IP
- **OAuth register:** Per IP address (`oauth:ip:{ip}`)
- **OAuth token:** Per IP + client_id (`oauth:ip:{ip}` + `oauth:client:{client_id}`)

### IP Detection

Client IP is extracted in order:
1. `X-Forwarded-For` header (first entry, for reverse proxy setups)
2. Direct client IP from the connection
3. Falls back to `"unknown"`

### Multi-key Limiting

OAuth endpoints use multi-key limiting (`check_rate_limit_multi`): **all keys must pass** for a request to be allowed. This prevents both IP-based flooding and per-client credential stuffing.

## Response

When rate limited, the server returns:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 60

{
  "error": "rate_limit_exceeded",
  "error_description": "Too many requests. Please try again later."
}
```

For MCP JSON-RPC endpoints, rate limiting returns error code `-32002`.

## Endpoints with Rate Limiting

| Endpoint | Keys Checked | Limit |
|----------|-------------|-------|
| `POST /api/v1/mcp` | Bearer token / IP | `rate_limit_rpm` (default 60/min) |
| `POST /api/v1/oauth/register` | IP | `rate_limit_rpm` |
| `POST /api/v1/oauth/token` | IP + client_id | `rate_limit_rpm` |

## Implementation

Source: `src/valence/server/rate_limit.py`

Key functions:
- `check_rate_limit(key, rpm_limit, window_seconds=60)` — Single-key check
- `check_rate_limit_multi(keys, rpm_limit, window_seconds=60)` — Multi-key check (all must pass)
- `check_oauth_rate_limit(request, client_id, rpm_limit)` — OAuth-specific (returns `RateLimitResult`)
- `clear_rate_limits()` — Reset state (for testing)
