#!/usr/bin/env bash
#
# sync-health-check.sh
# Health check for BMAD ↔ Linear sync infrastructure
#
# Validates:
# - Configuration file exists and is valid
# - linctl authentication works
# - State files are readable
# - Directory permissions correct
# - Linear API connectivity
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed

set -uo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Counters
PASSED=0
FAILED=0

# Find project root (directory containing .sync/)
PROJECT_ROOT=""
CURRENT_DIR="$(pwd)"
while [[ "$CURRENT_DIR" != "/" ]]; do
    if [[ -d "$CURRENT_DIR/.sync" ]]; then
        PROJECT_ROOT="$CURRENT_DIR"
        break
    fi
    CURRENT_DIR="$(dirname "$CURRENT_DIR")"
done

if [[ -z "$PROJECT_ROOT" ]]; then
    echo -e "${RED}✗ Could not find .sync/ directory${NC}"
    echo "  Run this command from project root or initialize with: mkdir -p .sync/config"
    exit 1
fi

echo "BMAD ↔ Linear Sync Health Check"
echo "================================"
echo ""

# Helper functions
check_pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASSED++))
}

check_fail() {
    echo -e "${RED}✗${NC} $1"
    if [[ -n "${2:-}" ]]; then
        echo "  → $2"
    fi
    ((FAILED++))
}

check_warn() {
    echo -e "${YELLOW}!${NC} $1"
    if [[ -n "${2:-}" ]]; then
        echo "  → $2"
    fi
}

# Check 1: Configuration file exists
echo "Checking configuration..."
CONFIG_FILE="$PROJECT_ROOT/.sync/config/sync_config.yaml"
if [[ -f "$CONFIG_FILE" ]]; then
    check_pass "Configuration file exists: $CONFIG_FILE"
else
    check_fail "Configuration file not found: $CONFIG_FILE" \
        "Create it following the template in docs-bmad/epic-1-context.md"
fi

# Check 2: Configuration is valid YAML
if [[ -f "$CONFIG_FILE" ]]; then
    if command -v yq >/dev/null 2>&1; then
        if yq eval '.' "$CONFIG_FILE" >/dev/null 2>&1; then
            check_pass "Configuration is valid YAML"
        else
            check_fail "Configuration has invalid YAML syntax" \
                "Run: yq eval '.' $CONFIG_FILE"
        fi
    else
        check_warn "yq not installed, skipping YAML validation" \
            "Install: brew install yq"
    fi
fi

# Check 3: Required Python libraries
echo ""
echo "Checking Python dependencies..."
if command -v python3 >/dev/null 2>&1; then
    check_pass "Python 3 available"

    # Check for required modules
    for module in yaml json; do
        if python3 -c "import $module" 2>/dev/null; then
            check_pass "Python module '$module' available"
        else
            check_fail "Python module '$module' not found" \
                "Install: pip install PyYAML"
        fi
    done
else
    check_fail "Python 3 not found" \
        "Install: brew install python3"
fi

# Check 4: linctl installation
echo ""
echo "Checking linctl CLI..."
if command -v linctl >/dev/null 2>&1; then
    VERSION=$(linctl --version 2>&1 || echo "unknown")
    check_pass "linctl installed: $VERSION"
else
    check_fail "linctl not found in PATH" \
        "Install: brew tap dorkitude/linctl && brew install linctl"
fi

# Check 5: Linear authentication
echo ""
echo "Checking Linear authentication..."
if command -v linctl >/dev/null 2>&1; then
    # Check for API key
    if [[ -n "${LINEAR_API_KEY:-}" ]]; then
        check_pass "LINEAR_API_KEY environment variable set"
    elif [[ -f "$HOME/.linctl-auth.json" ]]; then
        check_pass "linctl authentication file exists: ~/.linctl-auth.json"
    else
        check_fail "Linear authentication not configured" \
            "Set LINEAR_API_KEY or run: linctl auth"
    fi

    # Test authentication
    if linctl user me >/dev/null 2>&1; then
        USER_INFO=$(linctl user me 2>/dev/null || echo "{}")
        USER_NAME=$(echo "$USER_INFO" | python3 -c "import sys, json; print(json.load(sys.stdin).get('name', 'Unknown'))" 2>/dev/null || echo "Unknown")
        check_pass "Linear authentication works (User: $USER_NAME)"
    else
        check_fail "Linear authentication failed" \
            "Check LINEAR_API_KEY or run: linctl auth"
    fi
else
    check_warn "Skipping authentication check (linctl not installed)"
fi

# Check 6: Directory structure
echo ""
echo "Checking directory structure..."
for dir in config state logs cache backups; do
    DIR_PATH="$PROJECT_ROOT/.sync/$dir"
    if [[ -d "$DIR_PATH" ]]; then
        check_pass "Directory exists: .sync/$dir/"
    else
        check_fail "Directory missing: .sync/$dir/" \
            "Create: mkdir -p $DIR_PATH"
    fi
done

# Check 7: State file permissions
echo ""
echo "Checking permissions..."
STATE_DIR="$PROJECT_ROOT/.sync/state"
if [[ -d "$STATE_DIR" ]]; then
    PERMS=$(stat -f "%OLp" "$STATE_DIR" 2>/dev/null || stat -c "%a" "$STATE_DIR" 2>/dev/null)
    if [[ "$PERMS" == "700" ]]; then
        check_pass "State directory has correct permissions (700)"
    else
        check_warn "State directory permissions: $PERMS (recommended: 700)" \
            "Fix: chmod 700 $STATE_DIR"
    fi
fi

# Check 8: State files are readable
echo ""
echo "Checking state files..."
for state_file in content_index.json sync_state.json number_registry.json; do
    FILE_PATH="$PROJECT_ROOT/.sync/state/$state_file"
    if [[ -f "$FILE_PATH" ]]; then
        if [[ -r "$FILE_PATH" ]]; then
            # Validate JSON
            if python3 -c "import json; json.load(open('$FILE_PATH'))" 2>/dev/null; then
                check_pass "State file valid: $state_file"
            else
                check_fail "State file corrupted: $state_file" \
                    "Check backups in .sync/backups/"
            fi
        else
            check_fail "State file not readable: $state_file"
        fi
    else
        check_warn "State file not initialized: $state_file" \
            "Will be created on first sync"
    fi
done

# Check 9: Log file writable
echo ""
echo "Checking logging..."
LOG_DIR="$PROJECT_ROOT/.sync/logs"
if [[ -d "$LOG_DIR" ]]; then
    if [[ -w "$LOG_DIR" ]]; then
        check_pass "Log directory writable: .sync/logs/"
    else
        check_fail "Log directory not writable: .sync/logs/" \
            "Fix: chmod 755 $LOG_DIR"
    fi
fi

# Check 10: Linear API connectivity (if authenticated)
echo ""
echo "Checking Linear API connectivity..."
if command -v linctl >/dev/null 2>&1 && linctl user me >/dev/null 2>&1; then
    # Check team access
    if [[ -n "${LINEAR_TEAM:-}" ]]; then
        if linctl team list --plaintext | grep -q "$LINEAR_TEAM" 2>/dev/null; then
            check_pass "Linear team accessible: $LINEAR_TEAM"
        else
            check_fail "Linear team not found: $LINEAR_TEAM" \
                "Check team name or LINEAR_TEAM environment variable"
        fi
    else
        check_warn "LINEAR_TEAM not set" \
            "Set in environment or .sync/config/sync_config.yaml"
    fi

    # Check project access (if LINEAR_PROJECT set)
    if [[ -n "${LINEAR_PROJECT:-}" ]] && [[ -n "${LINEAR_TEAM:-}" ]]; then
        PROJ_LIST=$(linctl project list --team "$LINEAR_TEAM" --plaintext 2>/dev/null || true)
        if [[ -z "$PROJ_LIST" ]]; then
            PROJ_LIST=$(linctl project list --plaintext 2>/dev/null || true)
        fi
        if echo "$PROJ_LIST" | grep -q "$LINEAR_PROJECT"; then
            check_pass "Linear project accessible: $LINEAR_PROJECT"
        else
            check_fail "Linear project not found: $LINEAR_PROJECT" \
                "Check project name or LINEAR_PROJECT environment variable"
        fi
    fi
else
    check_warn "Skipping API connectivity check (authentication not working)"
fi

# Summary
echo ""
echo "================================"
echo "Summary"
echo "================================"
echo -e "${GREEN}Passed:${NC} $PASSED"
if [[ $FAILED -gt 0 ]]; then
    echo -e "${RED}Failed:${NC} $FAILED"
fi
echo ""

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo "Sync infrastructure is ready."
    exit 0
else
    echo -e "${RED}✗ $FAILED check(s) failed${NC}"
    echo "Fix the issues above before syncing."
    exit 1
fi
