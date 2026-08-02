#!/usr/bin/env bash
# HandAI TTS Lab - Runpod installer
# Installs the TTS Lab stack onto a Runpod GPU pod and verifies/repairs
# conda environments so the Web UI and launcher work after migration.
#
# Defaults assume a standard Runpod Ubuntu CUDA template:
#   - persistent workspace at /workspace
#   - conda root at /workspace/miniconda3
#   - TTS Lab app/data at /workspace/handai-tts-lab
#
# Usage:
#   ./install-runpod.sh [stack-installer-options]
#
# To repair an existing migrated pod:
#   /workspace/handai-tts-lab/repair-runpod-envs.sh
set -Eeuo pipefail

REPO_URL="${TTS_REPO_URL:-https://github.com/ChrisCantwell/handai-tts-lab.git}"
RUNPOD_LAB="${TTS_LAB:-/workspace/handai-tts-lab}"
RUNPOD_CONDA_ROOT="${CONDA_ROOT:-/workspace/miniconda3}"
RUNPOD_VIDEO_DL_DIR="${VIDEO_DL_DIR:-/root/video-dl}"

# Keep pip cache and temp files off the small Runpod root overlay.
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/workspace/.pip-cache}"
export TMPDIR="${TMPDIR:-/workspace/tmp}"
mkdir -p "$PIP_CACHE_DIR" "$TMPDIR"

LOG_ROOT="${RUNPOD_LAB}/logs/runpod-installer"
LOG_FILE="${LOG_ROOT}/install-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$LOG_ROOT"
LOG_FILE="${LOG_ROOT}/install-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$LOG_ROOT"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG_FILE"; }
warn() { printf '[%s] [WARN] %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG_FILE"; }
fail() { printf '[%s] [FAIL] %s\n' "$(date +%H:%M:%S)" "$*" >&2 | tee -a "$LOG_FILE" >/dev/null; exit 1; }

is_runpod() {
  [[ -d /workspace ]] && { [[ -d /etc/runpod-release ]] && return 0; command -v nvidia-smi >/dev/null && return 0; }
  return 1
}

detect_cuda() {
  if command -v nvidia-smi >/dev/null; then
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || true
  else
    warn "nvidia-smi not found. Runpod template usually has CUDA drivers."
  fi
}

clone_or_update_app() {
  log "App source: $REPO_URL"
  if [[ -d "${RUNPOD_LAB}/app/.git" ]]; then
    log "Updating existing app repo at ${RUNPOD_LAB}/app"
    git -C "${RUNPOD_LAB}/app" pull --ff-only || warn "git pull failed; continuing with existing code"
  else
    log "Cloning app repo into ${RUNPOD_LAB}/app"
    mkdir -p "${RUNPOD_LAB}"
    git clone "$REPO_URL" "${RUNPOD_LAB}/app"
  fi
}

# Robust recursive delete for Runpod's network-backed /workspace.
# Plain rm -rf can fail with "Directory not empty" on stale NFS-like entries.
rm_rf_robust() {
  local target="$1"
  [[ -e "$target" ]] || return 0
  chmod -R +w "$target" 2>/dev/null || true
  find "$target" -type f -delete 2>/dev/null || true
  for _ in {1..10}; do
    find "$target" -type d -empty -delete 2>/dev/null || true
    [[ ! -e "$target" ]] && return 0
  done
  rm -rf "$target" 2>/dev/null || true
}

base_conda_healthy() {
  local py_bin="${RUNPOD_CONDA_ROOT}/bin/python"
  [[ -x "$py_bin" ]] || return 1
  "$py_bin" -c "import encodings; print('base ok')" >/dev/null 2>&1
}

verify_env() {
  local env_name="$1"
  local py_bin="${RUNPOD_CONDA_ROOT}/envs/${env_name}/bin/python"
  [[ -x "$py_bin" ]] || return 1
  "$py_bin" -c "import encodings, sys; print('ok', sys.prefix)" >/dev/null 2>&1
}

collect_broken_envs() {
  local -n out="$1"
  out=()
  for env in tts-chatterbox tts-qwen3 tts-cosyvoice tts-whisper tts-f5 tts-whisperx tts-crisperwhisper; do
    if [[ -d "${RUNPOD_CONDA_ROOT}/envs/${env}" ]] && ! verify_env "$env"; then
      out+=("$env")
    fi
  done
}

# Shared core: detect broken base conda and/or envs, remove them, and run the
# stack installer to recreate them.
repair_or_install_stack() {
  local mode="$1"; shift
  local stack_script="${RUNPOD_LAB}/app/stack-installer/install-tts-lab-stack.sh"
  [[ -x "$stack_script" ]] || fail "Stack installer not found/executable: $stack_script"

  local -a broken=()
  collect_broken_envs broken

  local base_ok=0
  base_conda_healthy && base_ok=1 || true

  # In --install mode, make sure the default engines exist even if not broken.
  if [[ "$mode" == "--install" ]]; then
    for env in tts-chatterbox tts-qwen3 tts-cosyvoice tts-whisper; do
      if [[ ! -d "${RUNPOD_CONDA_ROOT}/envs/${env}" ]]; then
        broken+=("$env")
      fi
    done
  fi

  if [[ ${#broken[@]} -eq 0 && $base_ok -eq 1 ]]; then
    log "Base conda and all required environments look healthy."
    return 0
  fi

  if [[ ${#broken[@]} -gt 0 ]]; then
    warn "Broken/migrated environments detected: ${broken[*]}"
  fi

  # Optional-engine flags from the broken list.
  local flags=(--yes --skip-system-deps --no-video-dl "$@")
  for env in "${broken[@]}"; do
    case "$env" in
      tts-f5)         flags+=(--with-f5-experimental) ;;
      tts-whisperx)   flags+=(--with-whisperx) ;;
      tts-crisperwhisper) flags+=(--with-crisperwhisper) ;;
    esac
  done

  for env in "${broken[@]}"; do
    log "Removing broken env dir: ${RUNPOD_CONDA_ROOT}/envs/${env}"
    rm_rf_robust "${RUNPOD_CONDA_ROOT}/envs/${env}"
  done

  if [[ $base_ok -eq 0 ]]; then
    warn "Base conda is broken or missing; removing it for reinstallation."
    rm_rf_robust "${RUNPOD_CONDA_ROOT}"
  fi

  log "Running stack installer to recreate base conda and/or engines..."
  TTS_LAB="$RUNPOD_LAB" \
    CONDA_ROOT="$RUNPOD_CONDA_ROOT" \
    VIDEO_DL_DIR="$RUNPOD_VIDEO_DL_DIR" \
    PIP_CACHE_DIR="$PIP_CACHE_DIR" \
    TMPDIR="$TMPDIR" \
    bash "$stack_script" "${flags[@]}" || fail "Stack installer failed (log: $LOG_FILE)"

  # Re-verify.
  local -a still_broken=()
  collect_broken_envs still_broken
  base_conda_healthy && base_ok=1 || base_ok=0
  if [[ ${#still_broken[@]} -gt 0 || $base_ok -eq 0 ]]; then
    fail "Still broken after repair: ${still_broken[*]} (base_ok=$base_ok)"
  fi
  log "Base conda and all environments are usable."
}

# Place a repair helper script in the TTS Lab root for post-migration use.
write_repair_helper() {
  local target="${RUNPOD_LAB}/repair-runpod-envs.sh"
  local runpod_dir="${RUNPOD_LAB}/app/runpod"

  # If the repo has a runpod/ directory, create a thin wrapper. Otherwise,
  # embed a self-contained repair script so repair always works even before
  # the repo runpod/ folder is populated.
  if [[ -d "$runpod_dir" && -f "${runpod_dir}/repair-runpod-envs.sh" ]]; then
    cat > "$target" <<EOF
#!/usr/bin/env bash
# Auto-generated by install-runpod.sh
set -Eeuo pipefail
export TTS_LAB="${RUNPOD_LAB}"
export CONDA_ROOT="${RUNPOD_CONDA_ROOT}"
export VIDEO_DL_DIR="${RUNPOD_VIDEO_DL_DIR}"
"\${TTS_LAB}/app/runpod/repair-runpod-envs.sh"
EOF
  else
    log "Embedding standalone repair helper"
    cat > "$target" <<'REPAIR_EOF'
#!/usr/bin/env bash
# Auto-generated by install-runpod.sh
# Standalone repair script for a Runpod-migrated HandAI TTS Lab instance.
set -Eeuo pipefail

TTS_LAB="${TTS_LAB:-/workspace/handai-tts-lab}"
CONDA_ROOT="${CONDA_ROOT:-/workspace/miniconda3}"
VIDEO_DL_DIR="${VIDEO_DL_DIR:-/root/video-dl}"
STACK_INSTALLER="${TTS_LAB}/app/stack-installer/install-tts-lab-stack.sh"

# Keep pip cache and temp files off the small Runpod root overlay.
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-/workspace/.pip-cache}"
export TMPDIR="${TMPDIR:-/workspace/tmp}"
mkdir -p "$PIP_CACHE_DIR" "$TMPDIR"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '[%s] [WARN] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '[%s] [FAIL] %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

rm_rf_robust() {
  local target="$1"
  [[ -e "$target" ]] || return 0
  chmod -R +w "$target" 2>/dev/null || true
  find "$target" -type f -delete 2>/dev/null || true
  for _ in {1..10}; do
    find "$target" -type d -empty -delete 2>/dev/null || true
    [[ ! -e "$target" ]] && return 0
  done
  rm -rf "$target" 2>/dev/null || true
}

base_conda_healthy() {
  local py_bin="${CONDA_ROOT}/bin/python"
  [[ -x "$py_bin" ]] || return 1
  "$py_bin" -c "import encodings; print('base ok')" >/dev/null 2>&1
}

verify_env() {
  local env_name="$1"
  local py_bin="${CONDA_ROOT}/envs/${env_name}/bin/python"
  [[ -x "$py_bin" ]] || return 1
  "$py_bin" -c "import encodings, sys; print('ok', sys.prefix)" >/dev/null 2>&1
}

collect_broken_envs() {
  local -n out="$1"
  out=()
  for env in tts-chatterbox tts-qwen3 tts-cosyvoice tts-whisper tts-f5 tts-whisperx tts-crisperwhisper; do
    if [[ -d "${CONDA_ROOT}/envs/${env}" ]] && ! verify_env "$env"; then
      out+=("$env")
    fi
  done
}

main() {
  [[ -x "$STACK_INSTALLER" ]] || fail "Stack installer not found: $STACK_INSTALLER"

  log "Repairing Runpod TTS Lab conda environments"
  log "TTS_LAB=$TTS_LAB CONDA_ROOT=$CONDA_ROOT"

  local -a broken=()
  collect_broken_envs broken

  local base_ok=0
  base_conda_healthy && base_ok=1 || true

  if [[ ${#broken[@]} -eq 0 && $base_ok -eq 1 ]]; then
    log "Base conda and all existing environments look healthy."
    return 0
  fi

  if [[ ${#broken[@]} -gt 0 ]]; then
    warn "Broken/migrated environments detected: ${broken[*]}"
  fi

  local flags=(--yes --skip-system-deps --no-video-dl)
  for env in "${broken[@]}"; do
    case "$env" in
      tts-f5)         flags+=(--with-f5-experimental) ;;
      tts-whisperx)   flags+=(--with-whisperx) ;;
      tts-crisperwhisper) flags+=(--with-crisperwhisper) ;;
    esac
  done

  for env in "${broken[@]}"; do
    log "Removing broken env: ${CONDA_ROOT}/envs/${env}"
    rm_rf_robust "${CONDA_ROOT}/envs/${env}"
  done

  if [[ $base_ok -eq 0 ]]; then
    warn "Base conda is broken; removing it for reinstallation."
    rm_rf_robust "$CONDA_ROOT"
  fi

  log "Reinstalling affected engines and base conda if needed..."
  TTS_LAB="$TTS_LAB" CONDA_ROOT="$CONDA_ROOT" VIDEO_DL_DIR="$VIDEO_DL_DIR" \
    bash "$STACK_INSTALLER" "${flags[@]}" || fail "Repair install failed"

  local -a still_broken=()
  collect_broken_envs still_broken
  base_conda_healthy && base_ok=1 || base_ok=0
  if [[ ${#still_broken[@]} -gt 0 || $base_ok -eq 0 ]]; then
    fail "Still broken after repair: ${still_broken[*]} (base_ok=$base_ok)"
  fi

  log "Repair complete. All environments are usable."
}

main "$@"
REPAIR_EOF
  fi
  chmod +x "$target"
  log "Wrote repair helper: $target"
}

start_webui_service() {
  local service_name="tts-webui-runpod"
  local service_dir="${HOME}/.config/systemd/user"
  mkdir -p "$service_dir"

  cat > "${service_dir}/${service_name}.service" <<EOF
[Unit]
Description=HandAI TTS Web UI (Runpod)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=5
Environment=TTS_LAB=${RUNPOD_LAB}
Environment=TTS_APP_DIR=${RUNPOD_LAB}/app
Environment=TTS_DATA_DIR=${RUNPOD_LAB}/data
Environment=TTS_MODEL_DIR=${RUNPOD_LAB}/models
Environment=CONDA_ROOT=${RUNPOD_CONDA_ROOT}
ExecStart=${RUNPOD_LAB}/start-tts-webui.sh

[Install]
WantedBy=default.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable "$service_name"
  systemctl --user start "$service_name" || warn "Could not start $service_name (may require lingering user session)"
  log "Web UI user service installed: systemctl --user status $service_name"
}

print_summary() {
  local ip=""
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  cat <<EOF

==================== Runpod TTS Lab Install Summary ====================
TTS_LAB:      ${RUNPOD_LAB}
CONDA_ROOT:   ${RUNPOD_CONDA_ROOT}
Web UI:       http://127.0.0.1:7870  (inside the pod)
Pod IP:       ${ip:-unknown}
Log:          ${LOG_FILE}

Access from your local machine:
  ssh -N -L 9090:127.0.0.1:7870 -p <runpod-ssh-port> root@<pod-ip>
  then open http://localhost:9090/

Runpod proxy (if exposing port 7870 in template):
  https://<pod-id>-7870.runpod.io/

Repair after migration:
  ${RUNPOD_LAB}/repair-runpod-envs.sh
=======================================================================
EOF
}

install_ffmpeg() {
  local bin_dir="${RUNPOD_LAB}/bin"
  mkdir -p "$bin_dir"

  if [[ -x "${bin_dir}/ffmpeg" && -x "${bin_dir}/ffprobe" ]]; then
    log "Bundled ffmpeg already present: ${bin_dir}/ffmpeg"
    return 0
  fi

  log "Downloading static ffmpeg/ffprobe bundle for Runpod"
  local tmpdir="/tmp/ffmpeg-runpod-$$"
  mkdir -p "$tmpdir"
  local url="https://johnvansickle.com/ffmpeg/builds/ffmpeg-git-amd64-static.tar.xz"
  local tarball="${tmpdir}/ffmpeg-static.tar.xz"

  if command -v curl >/dev/null; then
    curl -LfsS "$url" -o "$tarball" || warn "curl download failed; will try apt fallback"
  else
    wget -q "$url" -O "$tarball" || warn "wget download failed; will try apt fallback"
  fi

  if [[ -f "$tarball" && -s "$tarball" ]]; then
    tar -xf "$tarball" -C "$tmpdir" --strip-components=1 2>/dev/null || true
    local extracted
    extracted="$(find "$tmpdir" -maxdepth 2 -type f -name ffmpeg | head -1)"
    if [[ -n "$extracted" ]]; then
      local extracted_dir
      extracted_dir="$(dirname "$extracted")"
      cp -f "${extracted_dir}/ffmpeg" "${bin_dir}/ffmpeg"
      cp -f "${extracted_dir}/ffprobe" "${bin_dir}/ffprobe" 2>/dev/null || true
      chmod +x "${bin_dir}/ffmpeg"
      [[ -f "${bin_dir}/ffprobe" ]] && chmod +x "${bin_dir}/ffprobe"
      log "Installed bundled ffmpeg: ${bin_dir}/ffmpeg"
    else
      warn "Could not locate ffmpeg binary inside tarball; trying apt fallback"
    fi
  fi

  rm -rf "$tmpdir"

  if [[ ! -x "${bin_dir}/ffmpeg" ]]; then
    log "Attempting apt-get install ffmpeg as fallback"
    if command -v apt-get >/dev/null; then
      apt-get update && apt-get install -y ffmpeg || warn "apt ffmpeg install failed"
    fi
  fi

  if [[ ! -x "${bin_dir}/ffmpeg" && ! -x /usr/bin/ffmpeg ]]; then
    warn "ffmpeg still not available; some Web UI features will be disabled"
  fi
}

# Patch launcher scripts so bundled ffmpeg is on PATH before any system binary.
patch_path_for_bundled_ffmpeg() {
  local bin_dir="${RUNPOD_LAB}/bin"
  [[ -d "$bin_dir" ]] || return 0

  for script in "${RUNPOD_LAB}/start-tts-webui.sh" "${RUNPOD_LAB}/tts-lab.sh"; do
    [[ -f "$script" ]] || continue
    if ! grep -q "${bin_dir}" "$script"; then
      log "Prepending ${bin_dir} to PATH in ${script}"
      sed -i "2iexport PATH=\"${bin_dir}:\${PATH:-}\"" "$script"
    fi
  done
}

main() {
  is_runpod || warn "This does not look like a Runpod pod. Continuing anyway."
  log "HandAI TTS Lab Runpod installer"
  log "TTS_LAB=$RUNPOD_LAB CONDA_ROOT=$RUNPOD_CONDA_ROOT"
  detect_cuda

  if [[ "${1:-}" == "--repair" ]]; then
    shift || true
    repair_or_install_stack --repair "$@"
    install_ffmpeg
    patch_path_for_bundled_ffmpeg
    write_repair_helper
    print_summary
    exit 0
  fi

  clone_or_update_app
  repair_or_install_stack --install "$@"
  install_ffmpeg
  patch_path_for_bundled_ffmpeg
  write_repair_helper
  start_webui_service
  print_summary
}

main "$@"
