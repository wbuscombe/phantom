#!/usr/bin/env bash
# Phantom VM Provisioning Script
# Provisions an Ubuntu 24.04 VM for running Phantom as a self-hosted service.
#
# Designed for TrueNAS-hosted VMs. Idempotent — safe to re-run.
#
# Usage:
#   sudo bash scripts/setup-vm.sh [--help]
#
# Prerequisites:
#   - Ubuntu 24.04 LTS (server or minimal)
#   - Root or sudo access
#   - Internet connectivity

set -euo pipefail

# ── Configuration ──────────────────────────────────────
PHANTOM_USER="phantom"
PHANTOM_HOME="/home/${PHANTOM_USER}"
PHANTOM_VAR="/var/phantom"
PHANTOM_ETC="/etc/phantom"
PHANTOM_WORKSPACE="/tmp/phantom/workspace"
NODE_MAJOR=22
PYTHON_MIN="3.12"
SWAP_SIZE="4G"
SWAP_FILE="/swapfile"

# ── Helpers ────────────────────────────────────────────
info()  { printf '\033[1;34m[INFO]\033[0m  %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m    %s\n' "$*"; }
warn()  { printf '\033[1;33m[WARN]\033[0m  %s\n' "$*"; }
err()   { printf '\033[1;31m[ERR]\033[0m   %s\n' "$*" >&2; }
step()  { printf '\n\033[1;36m── %s ──\033[0m\n' "$*"; }

die() { err "$@"; exit 1; }

check_root() {
    if [[ $EUID -ne 0 ]]; then
        die "This script must be run as root (use sudo)."
    fi
}

# ── Help ───────────────────────────────────────────────
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'USAGE'
Phantom VM Provisioning Script

Provisions an Ubuntu 24.04 VM with all dependencies needed to run
Phantom as a self-hosted documentation screenshot service.

Usage:
    sudo bash scripts/setup-vm.sh

What it installs:
  System   — UTC timezone, unattended-upgrades, swap (4 GB)
  Display  — Xvfb, Openbox, xdotool, maim, scrot
  Images   — ImageMagick, pngquant, oxipng (via cargo)
  Python   — Python 3.12+, pipx, phantom-docs
  Node     — Node.js 22 LTS (via NodeSource)
  Rust     — Rust stable toolchain, silicon, oxipng
  Browser  — Playwright Chromium (headless)
  Docker   — Docker CE
  Fonts    — JetBrains Mono, Inter, Noto Color Emoji
  Service  — systemd unit for `phantom serve`
  Firewall — UFW with SSH + Phantom port (9443)

All steps are idempotent — safe to re-run on an existing installation.

Environment:
    PHANTOM_USER      Service user (default: phantom)
    NODE_MAJOR        Node.js major version (default: 22)
    SWAP_SIZE         Swap file size (default: 4G)
USAGE
    exit 0
fi

check_root

# ── 1. System baseline ─────────────────────────────────
step "System baseline"

info "Setting timezone to UTC"
timedatectl set-timezone UTC 2>/dev/null || ln -sf /usr/share/zoneinfo/UTC /etc/localtime

info "Updating package index"
apt-get update -qq

info "Installing base packages"
apt-get install -y -qq \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    software-properties-common \
    unattended-upgrades \
    git \
    jq \
    htop \
    tmux \
    > /dev/null

info "Enabling unattended-upgrades"
dpkg-reconfigure -plow unattended-upgrades 2>/dev/null || true

ok "System baseline configured"

# ── 2. Swap ────────────────────────────────────────────
step "Swap (${SWAP_SIZE})"

if swapon --show | grep -q "${SWAP_FILE}"; then
    ok "Swap already active at ${SWAP_FILE}"
else
    if [[ ! -f "${SWAP_FILE}" ]]; then
        info "Creating ${SWAP_SIZE} swap file"
        fallocate -l "${SWAP_SIZE}" "${SWAP_FILE}"
        chmod 600 "${SWAP_FILE}"
        mkswap "${SWAP_FILE}"
    fi
    swapon "${SWAP_FILE}"
    if ! grep -q "${SWAP_FILE}" /etc/fstab; then
        echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
    fi
    # Prefer RAM, use swap as safety net
    sysctl -w vm.swappiness=10 > /dev/null
    if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
        echo "vm.swappiness=10" >> /etc/sysctl.conf
    fi
    ok "Swap configured"
fi

# ── 3. Phantom user ───────────────────────────────────
step "Phantom user"

if id "${PHANTOM_USER}" &>/dev/null; then
    ok "User '${PHANTOM_USER}' already exists"
else
    info "Creating system user '${PHANTOM_USER}'"
    useradd --system --shell /bin/bash --create-home --home-dir "${PHANTOM_HOME}" "${PHANTOM_USER}"
    ok "User '${PHANTOM_USER}' created"
fi

# ── 4. Display server (Xvfb + window manager) ────────
step "Display server"

info "Installing Xvfb, Openbox, and X11 utilities"
apt-get install -y -qq \
    xvfb \
    openbox \
    xdotool \
    xclip \
    maim \
    scrot \
    > /dev/null

ok "Display packages installed"

# ── 5. Image processing tools ─────────────────────────
step "Image processing tools"

info "Installing ImageMagick and pngquant"
apt-get install -y -qq \
    imagemagick \
    pngquant \
    > /dev/null

ok "Image tools installed"

# ── 6. Python ─────────────────────────────────────────
step "Python ${PYTHON_MIN}+"

if command -v python3 &>/dev/null; then
    PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    info "Found Python ${PYTHON_VER}"
else
    PYTHON_VER="0.0"
fi

# Install Python 3.12 if not present or too old
if python3 -c "import sys; exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
    ok "Python ${PYTHON_VER} satisfies >= ${PYTHON_MIN}"
else
    info "Installing Python ${PYTHON_MIN} from deadsnakes PPA"
    add-apt-repository -y ppa:deadsnakes/ppa > /dev/null 2>&1
    apt-get update -qq
    apt-get install -y -qq python3.12 python3.12-venv python3.12-dev > /dev/null
    # Do NOT use update-alternatives — changing the system python3 breaks apt_pkg
    # on Ubuntu 22.04. Instead, phantom uses python3.12 explicitly via pipx.
    ok "Python 3.12 installed"
fi

# Ensure pip and pipx (use system python for apt-managed packages)
info "Installing pip and pipx"
apt-get install -y -qq python3-pip python3-venv > /dev/null 2>&1 || true
# Install pipx for the phantom user via python3.12
sudo -u "${PHANTOM_USER}" python3.12 -m pip install --quiet --user pipx 2>/dev/null \
    || apt-get install -y -qq pipx > /dev/null 2>&1 \
    || true

ok "Python toolchain ready"

# ── 7. Node.js ────────────────────────────────────────
step "Node.js ${NODE_MAJOR} LTS"

if command -v node &>/dev/null; then
    NODE_VER=$(node --version | sed 's/^v//')
    NODE_CUR_MAJOR=$(echo "${NODE_VER}" | cut -d. -f1)
    if [[ "${NODE_CUR_MAJOR}" -ge "${NODE_MAJOR}" ]]; then
        ok "Node.js v${NODE_VER} satisfies >= ${NODE_MAJOR}"
    else
        warn "Node.js v${NODE_VER} is below ${NODE_MAJOR}, upgrading"
    fi
fi

if ! command -v node &>/dev/null || [[ "$(node --version | sed 's/^v//' | cut -d. -f1)" -lt "${NODE_MAJOR}" ]]; then
    info "Installing Node.js ${NODE_MAJOR} via NodeSource"
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - > /dev/null 2>&1
    apt-get install -y -qq nodejs > /dev/null
    ok "Node.js $(node --version) installed"
fi

# ── 8. Rust ───────────────────────────────────────────
step "Rust stable toolchain"

RUST_HOME="${PHANTOM_HOME}/.cargo"
if sudo -u "${PHANTOM_USER}" bash -c 'source "$HOME/.cargo/env" 2>/dev/null && rustc --version' &>/dev/null; then
    RUST_VER=$(sudo -u "${PHANTOM_USER}" bash -c 'source "$HOME/.cargo/env" && rustc --version' | awk '{print $2}')
    ok "Rust ${RUST_VER} already installed for ${PHANTOM_USER}"
else
    info "Installing Rust stable for ${PHANTOM_USER}"
    sudo -u "${PHANTOM_USER}" bash -c 'curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal 2>/dev/null'
    ok "Rust installed"
fi

# Install silicon and oxipng via cargo
info "Installing silicon and oxipng (cargo)"
# silicon needs XCB, harfbuzz, fontconfig, and freetype dev libs
apt-get install -y -qq \
    libfontconfig1-dev \
    libfreetype6-dev \
    libexpat1-dev \
    libxcb1-dev \
    libxcb-render0-dev \
    libxcb-shape0-dev \
    libxcb-xfixes0-dev \
    libharfbuzz-dev \
    > /dev/null

sudo -u "${PHANTOM_USER}" bash -c '
    source "$HOME/.cargo/env"
    command -v silicon  &>/dev/null || cargo install silicon  --quiet 2>/dev/null
    command -v oxipng   &>/dev/null || cargo install oxipng   --quiet 2>/dev/null
' || warn "Cargo installs may need manual completion (silicon/oxipng)"

ok "Rust tools ready"

# ── 9. Docker CE ──────────────────────────────────────
step "Docker CE"

if command -v docker &>/dev/null; then
    ok "Docker already installed ($(docker --version | awk '{print $3}' | tr -d ','))"
else
    info "Installing Docker CE"
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" \
      > /etc/apt/sources.list.d/docker.list

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin > /dev/null
    ok "Docker CE installed"
fi

# Add phantom user to docker group
if groups "${PHANTOM_USER}" | grep -q docker; then
    ok "${PHANTOM_USER} already in docker group"
else
    info "Adding ${PHANTOM_USER} to docker group"
    usermod -aG docker "${PHANTOM_USER}"
    ok "Added ${PHANTOM_USER} to docker group"
fi

# ── 10. Phantom (phantom-docs via pipx) ──────────────
step "Phantom (phantom-docs)"

if sudo -u "${PHANTOM_USER}" bash -c 'export PATH="$HOME/.local/bin:$PATH" && command -v phantom' &>/dev/null; then
    PHANTOM_VER=$(sudo -u "${PHANTOM_USER}" bash -c 'export PATH="$HOME/.local/bin:$PATH" && phantom --version 2>&1' | awk '{print $NF}')
    ok "Phantom ${PHANTOM_VER} already installed"
else
    info "Installing phantom-docs via pipx"
    sudo -u "${PHANTOM_USER}" bash -c 'export PATH="$HOME/.local/bin:$PATH" && pipx install --python python3.12 phantom-docs 2>/dev/null' \
        || sudo -u "${PHANTOM_USER}" bash -c 'python3.12 -m pipx install phantom-docs 2>/dev/null' \
        || warn "pipx install phantom-docs failed — install manually after setup"
    ok "Phantom installed"
fi

# ── 11. Playwright Chromium ───────────────────────────
step "Playwright Chromium"

info "Installing Playwright system dependencies"
apt-get install -y -qq \
    libnss3 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2t64 \
    libpango-1.0-0 \
    libcairo2 \
    libcups2 \
    libxkbcommon0 \
    libatspi2.0-0 \
    > /dev/null 2>&1 || apt-get install -y -qq \
    libnss3 libatk-bridge2.0-0 libdrm2 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libcups2 libxkbcommon0 libatspi2.0-0 \
    > /dev/null

info "Installing Playwright Chromium for ${PHANTOM_USER}"
sudo -u "${PHANTOM_USER}" bash -c '
    export PATH="$HOME/.local/bin:$PATH"
    playwright install chromium 2>/dev/null
' || warn "Playwright chromium install may need manual completion"

ok "Playwright ready"

# ── 12. Fonts ─────────────────────────────────────────
step "Fonts"

FONT_DIR="/usr/share/fonts/phantom"
mkdir -p "${FONT_DIR}"

install_font() {
    local name="$1"
    local url="$2"
    local dest_dir="${FONT_DIR}/${name}"
    if [[ -d "${dest_dir}" ]] && ls "${dest_dir}"/*.ttf &>/dev/null; then
        ok "Font ${name} already installed"
        return
    fi
    info "Installing font: ${name}"
    local tmpzip
    tmpzip=$(mktemp /tmp/font-XXXXXX.zip)
    if curl -fsSL "${url}" -o "${tmpzip}" 2>/dev/null; then
        mkdir -p "${dest_dir}"
        unzip -qo "${tmpzip}" -d "${dest_dir}" 2>/dev/null || true
        rm -f "${tmpzip}"
        ok "Font ${name} installed"
    else
        warn "Failed to download font ${name}"
        rm -f "${tmpzip}"
    fi
}

# JetBrains Mono (code screenshots)
install_font "JetBrainsMono" \
    "https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip"

# Inter (UI font)
install_font "Inter" \
    "https://github.com/rsms/inter/releases/download/v4.0/Inter-4.0.zip"

# Noto Color Emoji
apt-get install -y -qq fonts-noto-color-emoji > /dev/null 2>&1 || true

# Rebuild font cache
fc-cache -f > /dev/null 2>&1
ok "Font cache rebuilt"

# ── 13. Directory structure ───────────────────────────
step "Directory structure"

for dir in \
    "${PHANTOM_VAR}" \
    "${PHANTOM_VAR}/state" \
    "${PHANTOM_VAR}/logs" \
    "${PHANTOM_ETC}" \
    "${PHANTOM_WORKSPACE}" \
    "${PHANTOM_HOME}/projects" \
    "${PHANTOM_HOME}/.phantom"
do
    mkdir -p "${dir}"
done

# Ownership
chown -R "${PHANTOM_USER}:${PHANTOM_USER}" "${PHANTOM_VAR}"
chown -R "${PHANTOM_USER}:${PHANTOM_USER}" "${PHANTOM_HOME}"
chown -R "${PHANTOM_USER}:${PHANTOM_USER}" "${PHANTOM_WORKSPACE}"

# Config directory: root-owned, group-readable by phantom
chown root:"${PHANTOM_USER}" "${PHANTOM_ETC}"
chmod 750 "${PHANTOM_ETC}"

ok "Directories created"

# ── 14. Environment file template ─────────────────────
step "Configuration"

ENV_FILE="${PHANTOM_ETC}/phantom-serve.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    info "Creating environment file template at ${ENV_FILE}"
    cat > "${ENV_FILE}" <<'ENV'
# Phantom serve environment configuration
# See: docs/deployment-guide.md

# Required: HMAC secret for GitHub webhook signature validation
# Generate with: openssl rand -hex 32
PHANTOM_WEBHOOK_SECRET=

# Required: Mapping of repository names to manifest file paths
# Format: repo1=/path/to/manifest1.yml,repo2=/path/to/manifest2.yml
PHANTOM_MANIFEST_MAP=

# Optional: GitHub personal access token (for private repo clones)
# GITHUB_TOKEN=

# Optional: Anthropic API key (for AI Director features)
# ANTHROPIC_API_KEY=
ENV
    chown root:"${PHANTOM_USER}" "${ENV_FILE}"
    chmod 640 "${ENV_FILE}"
    ok "Environment file created — edit ${ENV_FILE} with your values"
else
    ok "Environment file already exists at ${ENV_FILE}"
fi

# ── 15. systemd service ──────────────────────────────
step "systemd service"

SERVICE_FILE="/etc/systemd/system/phantom.service"
info "Installing systemd unit"
cat > "${SERVICE_FILE}" <<UNIT
[Unit]
Description=Phantom Documentation Screenshot Service
Documentation=https://github.com/wbuscombe/phantom
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=${PHANTOM_USER}
Group=${PHANTOM_USER}

EnvironmentFile=${PHANTOM_ETC}/phantom-serve.env
Environment="PATH=${PHANTOM_HOME}/.local/bin:${PHANTOM_HOME}/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
Environment="DISPLAY=:99"
Environment="HOME=${PHANTOM_HOME}"

ExecStartPre=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
ExecStart=${PHANTOM_HOME}/.local/bin/phantom serve --port 9443

Restart=on-failure
RestartSec=10
TimeoutStopSec=30

# Working directory
WorkingDirectory=${PHANTOM_HOME}

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${PHANTOM_VAR} ${PHANTOM_WORKSPACE} ${PHANTOM_HOME}/.phantom /tmp

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=phantom

[Install]
WantedBy=multi-user.target
UNIT

# Xvfb service (virtual display for headless capture)
XVFB_SERVICE="/etc/systemd/system/phantom-xvfb.service"
cat > "${XVFB_SERVICE}" <<XVFB
[Unit]
Description=Xvfb Virtual Display for Phantom
Before=phantom.service

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
XVFB

systemctl daemon-reload
systemctl enable phantom-xvfb.service 2>/dev/null
systemctl enable phantom.service 2>/dev/null

ok "systemd units installed and enabled"
info "Start with: sudo systemctl start phantom-xvfb phantom"

# ── 16. UFW firewall ─────────────────────────────────
step "Firewall (UFW)"

if command -v ufw &>/dev/null; then
    info "Configuring UFW rules"
    ufw --force enable > /dev/null 2>&1 || true
    ufw allow ssh > /dev/null 2>&1
    ufw allow 9443/tcp comment "Phantom webhook" > /dev/null 2>&1
    ufw reload > /dev/null 2>&1
    ok "UFW configured (SSH + port 9443)"
else
    info "Installing UFW"
    apt-get install -y -qq ufw > /dev/null
    ufw default deny incoming > /dev/null 2>&1
    ufw default allow outgoing > /dev/null 2>&1
    ufw allow ssh > /dev/null 2>&1
    ufw allow 9443/tcp comment "Phantom webhook" > /dev/null 2>&1
    ufw --force enable > /dev/null 2>&1
    ok "UFW installed and configured"
fi

# ── 17. Post-install verification ────────────────────
step "Post-install verification"

PASS=0
FAIL=0

check_cmd() {
    local label="$1"
    local cmd="$2"
    if eval "${cmd}" &>/dev/null; then
        ok "${label}"
        ((PASS++)) || true
    else
        warn "MISSING: ${label}"
        ((FAIL++)) || true
    fi
}

check_cmd "git"               "command -v git"
check_cmd "python3 >= 3.12"   "python3 -c 'import sys; exit(0 if sys.version_info >= (3, 12) else 1)'"
check_cmd "node >= ${NODE_MAJOR}" "node --version"
check_cmd "npm"                "command -v npm"
check_cmd "docker"             "command -v docker"
check_cmd "Xvfb"              "command -v Xvfb"
check_cmd "xdotool"           "command -v xdotool"
check_cmd "maim"              "command -v maim"
check_cmd "pngquant"          "command -v pngquant"
check_cmd "ImageMagick"       "command -v convert"
check_cmd "fc-cache (fonts)"  "command -v fc-cache"
check_cmd "ufw"               "command -v ufw"

# Phantom-user tools (cargo, phantom, playwright)
check_cmd "rustc (phantom user)" \
    "sudo -u ${PHANTOM_USER} bash -c 'source \$HOME/.cargo/env 2>/dev/null && rustc --version'"
check_cmd "phantom (phantom user)" \
    "sudo -u ${PHANTOM_USER} bash -c 'export PATH=\$HOME/.local/bin:\$PATH && phantom --version'"

printf '\n'
info "${PASS} passed, ${FAIL} failed"

if [[ ${FAIL} -gt 0 ]]; then
    warn "Some checks failed. Review warnings above and fix before starting the service."
else
    ok "All checks passed!"
fi

# ── Summary ──────────────────────────────────────────
step "Setup complete"

cat <<SUMMARY

  Phantom VM provisioning finished.

  Next steps:
    1. Edit ${PHANTOM_ETC}/phantom-serve.env with your secrets
    2. Copy project manifests to ${PHANTOM_HOME}/projects/
    3. Start the services:
         sudo systemctl start phantom-xvfb
         sudo systemctl start phantom
    4. Verify:
         sudo bash scripts/verify-vm.sh
         curl http://localhost:9443/health

  Directories:
    Config:    ${PHANTOM_ETC}/
    State:     ${PHANTOM_VAR}/
    Projects:  ${PHANTOM_HOME}/projects/
    Workspace: ${PHANTOM_WORKSPACE}/

  Logs:
    sudo journalctl -u phantom -f

SUMMARY
