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
    # Check Valence health endpoint
    if curl -s -o /dev/null -w "%{http_code}" "https://$VALENCE_DOMAIN/api/v1/health" | grep -q "200"; then
        log_ok "Valence health endpoint is accessible"
    else
        log_error "Valence health endpoint is not accessible"
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
