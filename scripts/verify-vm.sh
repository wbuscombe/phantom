#!/usr/bin/env bash
# Phantom VM Verification Script
# Validates that a provisioned VM is healthy and ready to run Phantom.
#
# Usage:
#   sudo bash scripts/verify-vm.sh [--help]
#
# Exit codes:
#   0 — All checks passed
#   1 — One or more checks failed

set -euo pipefail

# ── Configuration ──────────────────────────────────────
PHANTOM_USER="phantom"
PHANTOM_HOME="/home/${PHANTOM_USER}"
PHANTOM_VAR="/var/phantom"
PHANTOM_ETC="/etc/phantom"
NODE_MAJOR=22

# ── Helpers ────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

pass() { printf "${GREEN}  ✓${NC} %s\n" "$*"; ((PASS++)); }
fail() { printf "${RED}  ✗${NC} %s\n" "$*"; ((FAIL++)); }
skip() { printf "${YELLOW}  ○${NC} %s\n" "$*"; ((WARN++)); }
section() { printf "\n${BOLD}${CYAN}── %s ──${NC}\n" "$*"; }

# ── Help ───────────────────────────────────────────────
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'USAGE'
Phantom VM Verification Script

Checks that all dependencies, services, and configuration are properly
set up for running Phantom.

Usage:
    sudo bash scripts/verify-vm.sh

Checks performed:
  - System tools (git, python3, node, npm, docker, pngquant, etc.)
  - Phantom user and directory structure
  - Rust toolchain and cargo binaries (silicon, oxipng)
  - Phantom CLI and Playwright browser
  - Fonts (JetBrains Mono, Inter, Noto Emoji)
  - systemd services (phantom, phantom-xvfb)
  - Firewall (UFW) rules
  - Environment configuration
  - Swap and disk space
USAGE
    exit 0
fi

if [[ $EUID -ne 0 ]]; then
    echo "This script should be run as root (use sudo) for full checks."
    echo "Some checks may be skipped."
    echo
fi

printf "${BOLD}Phantom VM Health Check${NC}\n"
printf "Date: %s\n" "$(date -u '+%Y-%m-%d %H:%M:%S UTC')"

# ── System tools ──────────────────────────────────────
section "System tools"

check_cmd() {
    local name="$1"
    shift
    if command -v "$1" &>/dev/null; then
        local ver
        ver=$("$@" 2>&1 | head -1) || ver="(version unknown)"
        pass "${name}: ${ver}"
    else
        fail "${name}: not found"
    fi
}

check_cmd "git"        git --version
check_cmd "python3"    python3 --version
check_cmd "node"       node --version
check_cmd "npm"        npm --version
check_cmd "docker"     docker --version
check_cmd "pngquant"   pngquant --version
check_cmd "convert"    convert --version
check_cmd "Xvfb"       Xvfb -version
check_cmd "xdotool"    xdotool --version
check_cmd "maim"       maim --version
check_cmd "jq"         jq --version
check_cmd "curl"       curl --version

# Python version check
if python3 -c "import sys; exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
    pass "Python >= 3.12"
else
    fail "Python >= 3.12 required (found $(python3 --version 2>&1))"
fi

# Node version check
if command -v node &>/dev/null; then
    NODE_VER=$(node --version | sed 's/^v//' | cut -d. -f1)
    if [[ "${NODE_VER}" -ge "${NODE_MAJOR}" ]]; then
        pass "Node.js >= ${NODE_MAJOR}"
    else
        fail "Node.js >= ${NODE_MAJOR} required (found v${NODE_VER})"
    fi
fi

# ── Phantom user ──────────────────────────────────────
section "Phantom user"

if id "${PHANTOM_USER}" &>/dev/null; then
    pass "User '${PHANTOM_USER}' exists"
else
    fail "User '${PHANTOM_USER}' does not exist"
fi

if groups "${PHANTOM_USER}" 2>/dev/null | grep -q docker; then
    pass "${PHANTOM_USER} is in docker group"
else
    fail "${PHANTOM_USER} is NOT in docker group"
fi

# ── Rust toolchain (as phantom user) ─────────────────
section "Rust toolchain (${PHANTOM_USER})"

if sudo -u "${PHANTOM_USER}" bash -c 'source "$HOME/.cargo/env" 2>/dev/null && rustc --version' &>/dev/null; then
    RUST_VER=$(sudo -u "${PHANTOM_USER}" bash -c 'source "$HOME/.cargo/env" && rustc --version')
    pass "rustc: ${RUST_VER}"
else
    fail "rustc not found for ${PHANTOM_USER}"
fi

if sudo -u "${PHANTOM_USER}" bash -c 'source "$HOME/.cargo/env" 2>/dev/null && command -v silicon' &>/dev/null; then
    pass "silicon installed"
else
    fail "silicon not found for ${PHANTOM_USER}"
fi

if sudo -u "${PHANTOM_USER}" bash -c 'source "$HOME/.cargo/env" 2>/dev/null && command -v oxipng' &>/dev/null; then
    pass "oxipng installed"
else
    fail "oxipng not found for ${PHANTOM_USER}"
fi

# ── Phantom CLI ───────────────────────────────────────
section "Phantom CLI"

if sudo -u "${PHANTOM_USER}" bash -c 'export PATH="$HOME/.local/bin:$PATH" && phantom --version' &>/dev/null; then
    PHANTOM_VER=$(sudo -u "${PHANTOM_USER}" bash -c 'export PATH="$HOME/.local/bin:$PATH" && phantom --version 2>&1')
    pass "phantom: ${PHANTOM_VER}"
else
    fail "phantom CLI not found for ${PHANTOM_USER}"
fi

# Playwright check
if sudo -u "${PHANTOM_USER}" bash -c 'export PATH="$HOME/.local/bin:$PATH" && python3 -c "from playwright.sync_api import sync_playwright"' &>/dev/null; then
    pass "Playwright Python bindings available"
else
    fail "Playwright Python bindings not found"
fi

# Check for Chromium browser
if sudo -u "${PHANTOM_USER}" bash -c 'export PATH="$HOME/.local/bin:$PATH" && playwright install --dry-run chromium 2>&1' | grep -qi "already installed\|up to date" 2>/dev/null; then
    pass "Playwright Chromium browser installed"
else
    skip "Playwright Chromium status uncertain (may still work)"
fi

# ── Fonts ─────────────────────────────────────────────
section "Fonts"

check_font() {
    local name="$1"
    if fc-list | grep -qi "${name}"; then
        pass "Font: ${name}"
    else
        fail "Font: ${name} not found"
    fi
}

check_font "JetBrains Mono"
check_font "Inter"
check_font "Noto Color Emoji"

# ── Directory structure ───────────────────────────────
section "Directories"

check_dir() {
    local path="$1" owner="$2"
    if [[ -d "${path}" ]]; then
        local actual_owner
        actual_owner=$(stat -c '%U' "${path}" 2>/dev/null || stat -f '%Su' "${path}" 2>/dev/null || echo "unknown")
        if [[ "${actual_owner}" == "${owner}" ]]; then
            pass "${path} (owner: ${owner})"
        else
            fail "${path} exists but owner is ${actual_owner}, expected ${owner}"
        fi
    else
        fail "${path} does not exist"
    fi
}

check_dir "${PHANTOM_VAR}"         "${PHANTOM_USER}"
check_dir "${PHANTOM_VAR}/state"   "${PHANTOM_USER}"
check_dir "${PHANTOM_VAR}/logs"    "${PHANTOM_USER}"
check_dir "${PHANTOM_ETC}"         "root"
check_dir "${PHANTOM_HOME}"        "${PHANTOM_USER}"

# ── Configuration ─────────────────────────────────────
section "Configuration"

ENV_FILE="${PHANTOM_ETC}/phantom-serve.env"
if [[ -f "${ENV_FILE}" ]]; then
    pass "Environment file exists: ${ENV_FILE}"

    # Check permissions (should be 640 root:phantom)
    PERMS=$(stat -c '%a' "${ENV_FILE}" 2>/dev/null || stat -f '%Lp' "${ENV_FILE}" 2>/dev/null || echo "unknown")
    if [[ "${PERMS}" == "640" ]]; then
        pass "Environment file permissions: ${PERMS}"
    else
        fail "Environment file permissions: ${PERMS} (expected 640)"
    fi

    # Check if secrets are configured (non-empty)
    if grep -q '^PHANTOM_WEBHOOK_SECRET=.\+' "${ENV_FILE}" 2>/dev/null; then
        pass "PHANTOM_WEBHOOK_SECRET is set"
    else
        skip "PHANTOM_WEBHOOK_SECRET is empty (configure before starting)"
    fi

    if grep -q '^PHANTOM_MANIFEST_MAP=.\+' "${ENV_FILE}" 2>/dev/null; then
        pass "PHANTOM_MANIFEST_MAP is set"
    else
        skip "PHANTOM_MANIFEST_MAP is empty (configure before starting)"
    fi
else
    fail "Environment file not found: ${ENV_FILE}"
fi

# ── systemd services ─────────────────────────────────
section "systemd services"

check_service() {
    local name="$1"
    if systemctl is-enabled "${name}" &>/dev/null; then
        pass "${name}: enabled"
    else
        fail "${name}: not enabled"
    fi

    if systemctl is-active "${name}" &>/dev/null; then
        pass "${name}: running"
    else
        skip "${name}: not running"
    fi
}

check_service "phantom.service"
check_service "phantom-xvfb.service"

# ── Firewall ──────────────────────────────────────────
section "Firewall (UFW)"

if command -v ufw &>/dev/null; then
    if ufw status | grep -q "Status: active"; then
        pass "UFW is active"

        if ufw status | grep -q "9443/tcp"; then
            pass "Port 9443/tcp allowed"
        else
            fail "Port 9443/tcp not in UFW rules"
        fi

        if ufw status | grep -q "22/tcp\|OpenSSH"; then
            pass "SSH access allowed"
        else
            fail "SSH access not in UFW rules"
        fi
    else
        fail "UFW is not active"
    fi
else
    fail "UFW is not installed"
fi

# ── Swap and disk ────────────────────────────────────
section "Resources"

# Swap
SWAP_TOTAL=$(free -m | awk '/^Swap:/ {print $2}')
if [[ "${SWAP_TOTAL}" -ge 2048 ]]; then
    pass "Swap: ${SWAP_TOTAL} MB (>= 2048 MB)"
elif [[ "${SWAP_TOTAL}" -gt 0 ]]; then
    skip "Swap: ${SWAP_TOTAL} MB (recommended >= 4096 MB)"
else
    fail "No swap configured"
fi

# Disk space
DISK_AVAIL=$(df -BG / | awk 'NR==2 {print $4}' | tr -d 'G')
if [[ "${DISK_AVAIL}" -ge 20 ]]; then
    pass "Disk available: ${DISK_AVAIL} GB (>= 20 GB)"
elif [[ "${DISK_AVAIL}" -ge 10 ]]; then
    skip "Disk available: ${DISK_AVAIL} GB (recommended >= 20 GB)"
else
    fail "Disk available: ${DISK_AVAIL} GB (< 10 GB, may be insufficient)"
fi

# RAM
RAM_TOTAL=$(free -m | awk '/^Mem:/ {print $2}')
if [[ "${RAM_TOTAL}" -ge 4096 ]]; then
    pass "RAM: ${RAM_TOTAL} MB (>= 4096 MB)"
elif [[ "${RAM_TOTAL}" -ge 2048 ]]; then
    skip "RAM: ${RAM_TOTAL} MB (recommended >= 4096 MB)"
else
    fail "RAM: ${RAM_TOTAL} MB (< 2048 MB, may be insufficient)"
fi

# ── Health endpoint ───────────────────────────────────
section "Health endpoint"

if systemctl is-active phantom.service &>/dev/null; then
    if curl -sf http://localhost:9443/health > /dev/null 2>&1; then
        HEALTH=$(curl -s http://localhost:9443/health)
        pass "Health endpoint: ${HEALTH}"
    else
        fail "Health endpoint not responding (service may be starting)"
    fi
else
    skip "Phantom service not running — skipping health check"
fi

# ── Summary ──────────────────────────────────────────
printf "\n${BOLD}── Summary ──${NC}\n"
printf "  ${GREEN}Passed:  %d${NC}\n" "${PASS}"
printf "  ${RED}Failed:  %d${NC}\n" "${FAIL}"
printf "  ${YELLOW}Skipped: %d${NC}\n" "${WARN}"
printf "\n"

if [[ ${FAIL} -eq 0 ]]; then
    printf "${GREEN}${BOLD}All checks passed!${NC} VM is ready for Phantom.\n"
    exit 0
else
    printf "${RED}${BOLD}%d check(s) failed.${NC} Review the output above.\n" "${FAIL}"
    exit 1
fi
