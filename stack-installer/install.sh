#!/usr/bin/env bash
# HandAI TTS Lab One-Line Installer
# Clones the repo and delegates to the versioned stack + webui installers.
set -Eeuo pipefail

VERSION="0.1.0"
DEFAULT_TTS_LAB="${HOME}/handai-tts-lab"
DEFAULT_CONDA_ROOT="${HOME}/miniconda3"
REPO_URL="${TTS_LAB_REPO_URL:-https://github.com/ChrisCantwell/handai-tts-lab.git}"
REPO_BRANCH="${TTS_LAB_REPO_BRANCH:-main}"

TTS_LAB="${TTS_LAB:-$DEFAULT_TTS_LAB}"
CONDA_ROOT="${CONDA_ROOT:-$DEFAULT_CONDA_ROOT}"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
fail() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<EOF
HandAI TTS Lab One-Line Installer v${VERSION}

Usage:
  curl -fsSL https://raw.githubusercontent.com/ChrisCantwell/handai-tts-lab/main/stack-installer/install.sh | bash

Environment overrides:
  TTS_LAB            Application root. Default: ${DEFAULT_TTS_LAB}
  CONDA_ROOT         Conda install root. Default: ${DEFAULT_CONDA_ROOT}
  TTS_LAB_REPO_URL   Git repository URL. Default: ${REPO_URL}
  TTS_LAB_REPO_BRANCH Git branch. Default: ${REPO_BRANCH}
  INSTALLER_ARGS     Extra args passed to the stack installer.

Examples:
  TTS_LAB=/opt/tts-lab bash install.sh
  bash install.sh -- --yes --skip-system-deps
EOF
}

# Parse only our own flags; everything after -- goes to the stack installer.
PASS_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --) shift; PASS_ARGS+=("$@"); break ;;
    *) PASS_ARGS+=("$1"); shift ;;
  esac
done

log "HandAI TTS Lab installer v${VERSION}"
log "Application root: ${TTS_LAB}"
log "Repository: ${REPO_URL} (${REPO_BRANCH})"

# Basic preflight
[[ "$(uname -s)" == "Linux" ]] || warn "This installer is designed for Linux. Continuing anyway."
command -v git >/dev/null || fail "git is required."
command -v bash >/dev/null || fail "bash is required."
command -v curl >/dev/null || command -v wget >/dev/null || fail "curl or wget is required."

mkdir -p "${TTS_LAB}"
APP_DIR="${TTS_LAB}/app"

# Clone or update application code
if [[ -d "${APP_DIR}/.git" ]]; then
  log "Updating existing app checkout: ${APP_DIR}"
  git -C "${APP_DIR}" fetch origin
  git -C "${APP_DIR}" checkout "${REPO_BRANCH}" || true
  git -C "${APP_DIR}" pull --ff-only origin "${REPO_BRANCH}" || warn "App pull failed; using existing checkout."
else
  log "Cloning HandAI TTS Lab into ${APP_DIR}"
  rm -rf "${APP_DIR}"
  git clone --branch "${REPO_BRANCH}" --depth 1 "${REPO_URL}" "${APP_DIR}"
fi

# Verify expected installer files exist
STACK_INSTALLER="${APP_DIR}/stack-installer/install-tts-lab-stack.sh"
WEBUI_INSTALLER="${APP_DIR}/webui/install.sh"
[[ -x "${STACK_INSTALLER}" ]] || fail "Stack installer not found or not executable: ${STACK_INSTALLER}"
[[ -x "${WEBUI_INSTALLER}" ]] || fail "Web UI installer not found or not executable: ${WEBUI_INSTALLER}"

# Run stack installer (engines, models, launchers)
log "Running stack installer..."
TTS_LAB="${TTS_LAB}" CONDA_ROOT="${CONDA_ROOT}" "${STACK_INSTALLER}" "${PASS_ARGS[@]:-}"

# Run web UI installer (copy Python files, write start scripts)
log "Running web UI installer..."
TTS_LAB="${TTS_LAB}" CONDA_ROOT="${CONDA_ROOT}" "${WEBUI_INSTALLER}"

log "Installation complete. Start the web UI with:"
log "  ${TTS_LAB}/start-tts-webui.sh"
