#!/usr/bin/env bash
# Standalone repair script for a Runpod-migrated HandAI TTS Lab instance.
# Removes broken conda envs and reinstalls them via the stack installer.
set -Eeuo pipefail

TTS_LAB="${TTS_LAB:-/workspace/handai-tts-lab}"
CONDA_ROOT="${CONDA_ROOT:-/workspace/miniconda3}"
VIDEO_DL_DIR="${VIDEO_DL_DIR:-/root/video-dl}"
STACK_INSTALLER="${TTS_LAB}/app/stack-installer/install-tts-lab-stack.sh"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '[%s] [WARN] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '[%s] [FAIL] %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

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

  # Determine optional-engine flags from the broken list.
  local flags=(--yes --skip-system-deps --no-video-dl)
  for env in "${broken[@]}"; do
    case "$env" in
      tts-f5)         flags+=(--with-f5-experimental) ;;
      tts-whisperx)   flags+=(--with-whisperx) ;;
      tts-crisperwhisper) flags+=(--with-crisperwhisper) ;;
    esac
  done

  # Wipe broken env directories first so the installer recreates them.
  for env in "${broken[@]}"; do
    log "Removing broken env: ${CONDA_ROOT}/envs/${env}"
    rm_rf_robust "${CONDA_ROOT}/envs/${env}"
  done

  # If base conda is broken, wipe it so the installer reinstalls Miniforge.
  if [[ $base_ok -eq 0 ]]; then
    warn "Base conda is broken; removing it for reinstallation."
    rm_rf_robust "$CONDA_ROOT"
  fi

  log "Reinstalling affected engines and base conda if needed..."
  TTS_LAB="$TTS_LAB" CONDA_ROOT="$CONDA_ROOT" VIDEO_DL_DIR="$VIDEO_DL_DIR" \
    bash "$STACK_INSTALLER" "${flags[@]}" || fail "Repair install failed"

  # Re-verify.
  local -a still_broken=()
  collect_broken_envs still_broken
  base_conda_healthy && base_ok=1 || base_ok=0
  if [[ ${#still_broken[@]} -gt 0 || $base_ok -eq 0 ]]; then
    fail "Still broken after repair: ${still_broken[*]} (base_ok=$base_ok)"
  fi

  log "Repair complete. All environments are usable."
}

main "$@"
