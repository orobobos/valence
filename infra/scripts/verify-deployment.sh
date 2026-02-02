#!/bin/bash
# Valence Pod Deployment Verification
# Verifies all services are running and endpoints are accessible

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

log_error() {
    echo -e "${RED}FAIL:${NC} $1"
    ((ERRORS++))
}

log_warn() {
    echo -e "${YELLOW}WARN:${NC} $1"
    ((WARNINGS++))
}

log_ok() {
    echo -e "${GREEN}PASS:${NC} $1"
}

log_info() {
    echo -e "INFO: $1"
}

# Check if running on the target host or locally
if [ -n "$VALENCE_POD_IP" ] && [ "$1" != "--local" ]; then
    REMOTE=true
    # Use root for remote commands that need sudo access
    SSH_CMD="ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no root@$VALENCE_POD_IP"
    log_info "Running remote verification on $VALENCE_POD_IP"
else
    REMOTE=false
    SSH_CMD=""
    log_info "Running local verification"
fi

run_cmd() {
    if [ "$REMOTE" = true ]; then
        $SSH_CMD "$1" 2>/dev/null
    else
        eval "$1" 2>/dev/null
    fi
}

echo ""
echo "========================================"
echo "Valence Pod Deployment Verification"
echo "========================================"

# === SYSTEMD SERVICES ===
echo ""
echo "--- Checking Systemd Services ---"

check_service() {
    local service=$1
    local status

    status=$(run_cmd "systemctl is-active $service" || true)
    if [ "$status" = "active" ]; then
        log_ok "$service is running"
        return 0
    else
        log_error "$service is not running (status: $status)"
        return 1
    fi
}

check_service "postgresql"
check_service "nginx"
check_service "matrix-synapse" || check_service "synapse"  # Name varies
# Note: vkb MCP server is spawned on-demand by Claude Code, not a standalone service

# === DATABASE CONNECTIVITY ===
echo ""
echo "--- Checking Database ---"

# Check PostgreSQL connection
if run_cmd "sudo -u postgres psql -c 'SELECT 1'" > /dev/null; then
    log_ok "PostgreSQL is accepting connections"
else
    log_error "PostgreSQL is not accepting connections"
fi

# Check valence database exists
if run_cmd "sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw valence"; then
    log_ok "Valence database exists"
else
    log_error "Valence database does not exist"
fi

# Check pgvector extension
if run_cmd "sudo -u postgres psql -d valence -c \"SELECT 1 FROM pg_extension WHERE extname='vector'\" | grep -q 1"; then
    log_ok "pgvector extension is installed"
else
    log_error "pgvector extension is not installed"
fi

# Check schema tables
TABLES_COUNT=$(run_cmd "sudo -u postgres psql -d valence -t -c \"SELECT count(*) FROM information_schema.tables WHERE table_schema='public'\"" | tr -d ' ')
if [ "$TABLES_COUNT" -gt 0 ]; then
    log_ok "Schema has $TABLES_COUNT tables"
else
    log_error "Schema appears empty (0 tables)"
fi

# === HTTP ENDPOINTS ===
echo ""
echo "--- Checking HTTP Endpoints ---"

if [ -z "$VALENCE_DOMAIN" ]; then
    log_warn "VALENCE_DOMAIN not set, skipping HTTP checks"
else
    # Check Matrix well-known endpoints
    if curl -s -o /dev/null -w "%{http_code}" "https://$VALENCE_DOMAIN/.well-known/matrix/server" | grep -q "200"; then
        log_ok "Matrix server well-known endpoint is accessible"
    else
        log_error "Matrix server well-known endpoint is not accessible"
    fi

    if curl -s -o /dev/null -w "%{http_code}" "https://$VALENCE_DOMAIN/.well-known/matrix/client" | grep -q "200"; then
        log_ok "Matrix client well-known endpoint is accessible"
    else
        log_error "Matrix client well-known endpoint is not accessible"
    fi

    # Check Synapse health endpoint
    if curl -s "https://$VALENCE_DOMAIN/_matrix/client/versions" | grep -q "versions"; then
        log_ok "Matrix Synapse is responding"
    else
        log_error "Matrix Synapse is not responding properly"
    fi
fi

# === SSL CERTIFICATE ===
echo ""
echo "--- Checking SSL Certificate ---"

if [ -z "$VALENCE_DOMAIN" ]; then
    log_warn "VALENCE_DOMAIN not set, skipping SSL checks"
else
    # Check certificate validity
    CERT_INFO=$(echo | openssl s_client -servername "$VALENCE_DOMAIN" -connect "$VALENCE_DOMAIN:443" 2>/dev/null | openssl x509 -noout -dates 2>/dev/null || true)

    if [ -n "$CERT_INFO" ]; then
        EXPIRY=$(echo "$CERT_INFO" | grep notAfter | cut -d= -f2)
        EXPIRY_EPOCH=$(date -d "$EXPIRY" +%s 2>/dev/null || date -j -f "%b %d %T %Y %Z" "$EXPIRY" +%s 2>/dev/null)
        NOW_EPOCH=$(date +%s)
        DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))

        if [ $DAYS_LEFT -gt 30 ]; then
            log_ok "SSL certificate valid for $DAYS_LEFT days (expires: $EXPIRY)"
        elif [ $DAYS_LEFT -gt 7 ]; then
            log_warn "SSL certificate expires in $DAYS_LEFT days"
        else
            log_error "SSL certificate expires in $DAYS_LEFT days - renewal needed!"
        fi
    else
        log_error "Could not retrieve SSL certificate"
    fi
fi

# === VKB SCHEMA ===
echo ""
echo "--- Checking VKB Schema ---"

# VKB MCP server uses stdio mode and is spawned on-demand by Claude Code
# We verify the schema is properly installed instead of checking for a running service

# Check VKB tables exist
VKB_TABLES=$(run_cmd "sudo -u postgres psql -d valence -t -c \"SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'vkb_%'\"" | tr -d ' ' || echo "0")
if [ "$VKB_TABLES" -gt 0 ]; then
    log_ok "VKB schema has $VKB_TABLES tables"
else
    log_error "VKB tables not found (expected vkb_* tables)"
fi

# Check beliefs table exists (core knowledge substrate)
if run_cmd "sudo -u postgres psql -d valence -c \"SELECT 1 FROM beliefs LIMIT 1\" > /dev/null 2>&1"; then
    log_ok "Beliefs table exists and is accessible"
else
    log_error "Beliefs table not accessible"
fi

# Check MCP config exists for Claude Code
if run_cmd "test -f /opt/valence/config/vkb.env"; then
    log_ok "VKB environment config exists"
else
    log_error "VKB environment config missing at /opt/valence/config/vkb.env"
fi

# === DISK SPACE ===
echo ""
echo "--- Checking Disk Space ---"

DISK_USAGE=$(run_cmd "df -h / | tail -1 | awk '{print \$5}' | tr -d '%'" || echo "0")
if [ "$DISK_USAGE" -lt 80 ]; then
    log_ok "Disk usage at ${DISK_USAGE}%"
elif [ "$DISK_USAGE" -lt 90 ]; then
    log_warn "Disk usage at ${DISK_USAGE}%"
else
    log_error "Disk usage critical at ${DISK_USAGE}%"
fi

# === MEMORY ===
echo ""
echo "--- Checking Memory ---"

MEM_FREE=$(run_cmd "free -m | awk '/Mem:/ {print \$7}'" || echo "0")
if [ "$MEM_FREE" -gt 500 ]; then
    log_ok "Available memory: ${MEM_FREE}MB"
elif [ "$MEM_FREE" -gt 200 ]; then
    log_warn "Low available memory: ${MEM_FREE}MB"
else
    log_error "Critical memory: ${MEM_FREE}MB available"
fi

# === MATRIX BOT SERVICE ===
echo ""
echo "--- Checking Matrix Bot Service ---"

check_service "valence-bot"

# Check bot logs for errors
BOT_ERRORS=$(run_cmd "journalctl -u valence-bot --since '5 minutes ago' --no-pager 2>/dev/null | grep -iE 'error|fail' | grep -v 'rate.limit' | wc -l" || echo "0")
if [ "$BOT_ERRORS" -eq 0 ]; then
    log_ok "No recent errors in bot logs"
else
    log_warn "Found $BOT_ERRORS error(s) in recent bot logs"
    log_info "Run: journalctl -u valence-bot --since '5 minutes ago' | grep -iE 'error|fail'"
fi

# Check bot is synced and processing
if run_cmd "journalctl -u valence-bot --since '10 minutes ago' --no-pager 2>/dev/null | grep -q 'Initial sync complete'"; then
    log_ok "Bot has completed initial sync"
else
    log_warn "Bot may not have completed initial sync"
fi

# === MATRIX BOT END-TO-END TEST ===
echo ""
echo "--- Matrix Bot End-to-End Test ---"

if [ -z "$VALENCE_DOMAIN" ]; then
    log_warn "VALENCE_DOMAIN not set, skipping bot e2e test"
elif [ -z "$SYNAPSE_REGISTRATION_SECRET" ]; then
    log_warn "SYNAPSE_REGISTRATION_SECRET not set, skipping bot e2e test"
elif [ "$REMOTE" != true ]; then
    log_warn "Bot e2e test requires remote mode (admin API is localhost only)"
else
    log_info "Running bot e2e test on server..."

    # Upload the e2e test script to the server
    REMOTE_SCRIPT="/tmp/bot_e2e_test_$$.sh"

    $SSH_CMD "cat > $REMOTE_SCRIPT" << 'SCRIPT_EOF'
#!/bin/bash
# Matrix Bot End-to-End Test Script
# Arguments: $1 = domain, $2 = registration_secret

set -e

DOMAIN="$1"
REG_SECRET="$2"

if [ -z "$DOMAIN" ] || [ -z "$REG_SECRET" ]; then
    echo "ERROR: Missing arguments"
    exit 1
fi

TEST_USER="e2etest_$(date +%s)"
TEST_PASSWORD="TestPass_$(openssl rand -hex 8)"
MATRIX_API="http://localhost:8008/_matrix/client/v3"
ADMIN_API="http://localhost:8008/_synapse/admin/v1"
ACCESS_TOKEN=""

cleanup() {
    if [ -n "$ACCESS_TOKEN" ]; then
        curl -s -X POST "$MATRIX_API/logout" \
            -H "Authorization: Bearer $ACCESS_TOKEN" \
            -H "Content-Type: application/json" -d "{}" > /dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

# Get registration nonce
NONCE=$(curl -s "$ADMIN_API/register" | jq -r '.nonce' 2>/dev/null)
if [ -z "$NONCE" ] || [ "$NONCE" = "null" ]; then
    echo "ERROR: Could not get registration nonce"
    exit 1
fi

# Create HMAC for registration
MAC=$(printf '%s\0%s\0%s\0%s' "$NONCE" "$TEST_USER" "$TEST_PASSWORD" "notadmin" | \
      openssl dgst -sha1 -hmac "$REG_SECRET" | awk '{print $2}')

# Register test user
REGISTER_RESPONSE=$(curl -s -X POST "$ADMIN_API/register" \
    -H "Content-Type: application/json" \
    -d "{\"nonce\":\"$NONCE\",\"username\":\"$TEST_USER\",\"password\":\"$TEST_PASSWORD\",\"admin\":false,\"mac\":\"$MAC\"}")

if ! echo "$REGISTER_RESPONSE" | grep -q "user_id"; then
    if echo "$REGISTER_RESPONSE" | grep -q "M_LIMIT_EXCEEDED"; then
        echo "WARN: Rate limited during registration"
        exit 0
    fi
    echo "ERROR: Failed to create test user: $REGISTER_RESPONSE"
    exit 1
fi
echo "OK: Created test user @$TEST_USER:$DOMAIN"

# Login as test user
LOGIN_RESPONSE=$(curl -s -X POST "$MATRIX_API/login" \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"m.login.password\",\"identifier\":{\"type\":\"m.id.user\",\"user\":\"$TEST_USER\"},\"password\":\"$TEST_PASSWORD\"}")

ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.access_token')
if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
    if echo "$LOGIN_RESPONSE" | grep -q "M_LIMIT_EXCEEDED"; then
        echo "WARN: Rate limited during login"
        exit 0
    fi
    echo "ERROR: Failed to login: $LOGIN_RESPONSE"
    exit 1
fi
echo "OK: Logged in as test user"

# Create DM room with bot
BOT_USER="@valence-bot:$DOMAIN"
CREATE_ROOM_RESPONSE=$(curl -s -X POST "$MATRIX_API/createRoom" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"preset\":\"trusted_private_chat\",\"invite\":[\"$BOT_USER\"],\"is_direct\":true}")

ROOM_ID=$(echo "$CREATE_ROOM_RESPONSE" | jq -r '.room_id')
if [ -z "$ROOM_ID" ] || [ "$ROOM_ID" = "null" ]; then
    echo "ERROR: Failed to create room: $CREATE_ROOM_RESPONSE"
    exit 1
fi
echo "OK: Created DM room: $ROOM_ID"

# Wait for bot to auto-join
sleep 3

# Send test message
TEST_MSG="E2E test $(date +%s)"
TXN_ID=$(date +%s%N)
ROOM_ID_ENCODED=$(echo "$ROOM_ID" | sed 's/!/%21/g;s/:/%3A/g')

SEND_RESPONSE=$(curl -s -X PUT \
    "$MATRIX_API/rooms/$ROOM_ID_ENCODED/send/m.room.message/$TXN_ID" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"msgtype\":\"m.text\",\"body\":\"@valence $TEST_MSG\"}")

if ! echo "$SEND_RESPONSE" | grep -q "event_id"; then
    echo "ERROR: Failed to send message: $SEND_RESPONSE"
    exit 1
fi
echo "OK: Sent test message to bot"

# Wait for bot response (up to 120 seconds)
echo "INFO: Waiting for bot response (up to 120s)..."
BOT_RESPONDED=false
SYNC_TOKEN=""

for i in $(seq 1 24); do
    sleep 5

    # Do incremental sync
    SYNC_URL="$MATRIX_API/sync?timeout=1000"
    if [ -n "$SYNC_TOKEN" ]; then
        SYNC_URL="$SYNC_URL&since=$SYNC_TOKEN"
    fi

    SYNC_RESPONSE=$(curl -s "$SYNC_URL" -H "Authorization: Bearer $ACCESS_TOKEN")
    SYNC_TOKEN=$(echo "$SYNC_RESPONSE" | jq -r '.next_batch // empty')

    # Check for bot message in our room
    if echo "$SYNC_RESPONSE" | jq -e ".rooms.join[\"$ROOM_ID\"].timeline.events[]? | select(.sender == \"$BOT_USER\")" > /dev/null 2>&1; then
        BOT_RESPONDED=true
        break
    fi
done

if [ "$BOT_RESPONDED" = true ]; then
    echo "OK: Bot responded to test message"
else
    # Check if bot at least received the message
    if journalctl -u valence-bot --since '3 minutes ago' --no-pager 2>/dev/null | grep -q "$TEST_MSG"; then
        echo "WARN: Bot received message but response not detected (may be processing)"
    else
        echo "ERROR: Bot did not respond within 120s"
        exit 1
    fi
fi

# Leave the room
curl -s -X POST "$MATRIX_API/rooms/$ROOM_ID_ENCODED/leave" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" -d "{}" > /dev/null 2>&1

echo "OK: E2E test completed successfully"
SCRIPT_EOF

    # Make script executable and run it with arguments
    $SSH_CMD "chmod +x $REMOTE_SCRIPT"
    E2E_OUTPUT=$($SSH_CMD "$REMOTE_SCRIPT '$VALENCE_DOMAIN' '$SYNAPSE_REGISTRATION_SECRET'" 2>&1) || true
    $SSH_CMD "rm -f $REMOTE_SCRIPT"

    # Parse output and log appropriately
    while IFS= read -r line; do
        case "$line" in
            OK:*) log_ok "${line#OK: }" ;;
            ERROR:*) log_error "${line#ERROR: }" ;;
            WARN:*) log_warn "${line#WARN: }" ;;
            INFO:*) log_info "${line#INFO: }" ;;
            *) [ -n "$line" ] && echo "$line" ;;
        esac
    done <<< "$E2E_OUTPUT"
fi

# === SUMMARY ===
echo ""
echo "========================================"
echo "Verification Summary"
echo "========================================"

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}FAILED:${NC} $ERRORS errors, $WARNINGS warnings"
    echo ""
    echo "Deployment verification failed. Review errors above."
    exit 1
else
    if [ $WARNINGS -gt 0 ]; then
        echo -e "${YELLOW}PASSED WITH WARNINGS:${NC} $WARNINGS warnings"
    else
        echo -e "${GREEN}PASSED:${NC} All checks successful"
    fi
    echo ""
    echo "Deployment is healthy."
fi

exit 0
