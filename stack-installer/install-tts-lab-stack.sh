#!/usr/bin/env bash
# HandAI TTS Lab Stack Installer v1.0.0
# Creates the engine stack and runtime layout for the HandAI TTS Lab Web UI.
#
# Default layout (self-contained application directory):
#   ~/handai-tts-lab/
#     app/         cloned handai-tts-lab repo (replaceable on upgrade)
#     data/        user data: output/, projects/, references/, config/
#     models/      downloaded weights and caches
#     backups/     backup archives
#     engines/     engine-specific non-conda artifacts
#     logs/        installer and runtime logs
#     tmp/         ephemeral working files
#
# For the previous flat layout, set TTS_LAB=/home/user/tts-lab.
set -Eeuo pipefail

VERSION="1.0.0"
DEFAULT_TTS_LAB="${HOME}/handai-tts-lab"
DEFAULT_CONDA_ROOT="${HOME}/miniconda3"
DEFAULT_VIDEO_DL_DIR="${HOME}/video-dl"
DEFAULT_VIDEO_DL_REPO="https://github.com/ChrisCantwell/handai-videodownloader.git"

TTS_LAB="${TTS_LAB:-$DEFAULT_TTS_LAB}"
CONDA_ROOT="${CONDA_ROOT:-$DEFAULT_CONDA_ROOT}"
VIDEO_DL_DIR="${VIDEO_DL_DIR:-$DEFAULT_VIDEO_DL_DIR}"
VIDEO_DL_REPO="${VIDEO_DL_REPO:-$DEFAULT_VIDEO_DL_REPO}"
PYTORCH_CUDA_INDEX="${PYTORCH_CUDA_INDEX:-https://download.pytorch.org/whl/cu124}"
COSY_TORCH_INDEX="${COSY_TORCH_INDEX:-https://download.pytorch.org/whl/cu121}"

# Layout subdirectories
TTS_APP_DIR="${TTS_APP_DIR:-${TTS_LAB}/app}"
TTS_DATA_DIR="${TTS_DATA_DIR:-${TTS_LAB}/data}"
TTS_MODEL_DIR="${TTS_MODEL_DIR:-${TTS_LAB}/models}"
TTS_OUT="${TTS_OUT:-${TTS_DATA_DIR}/output}"
TTS_REF="${TTS_REF:-${TTS_DATA_DIR}/references}"
TTS_JOB_DIR="${TTS_JOB_DIR:-${TTS_OUT}/job_history}"
TTS_TAGGED_WORKSPACE_DIR="${TTS_TAGGED_WORKSPACE_DIR:-${TTS_DATA_DIR}/projects/tagged-script}"
TTS_CONFIG_DIR="${TTS_CONFIG_DIR:-${TTS_DATA_DIR}/config}"
TTS_BACKUP_DIR="${TTS_BACKUP_DIR:-${TTS_LAB}/backups}"
TTS_LOGS_DIR="${TTS_LOGS_DIR:-${TTS_LAB}/logs}"
TTS_TMP_DIR="${TTS_TMP_DIR:-${TTS_LAB}/tmp}"

# Engine selection flags
INSTALL_SYSTEM_DEPS=1
INSTALL_VIDEO_DL=1
INSTALL_ENGINES=1
INSTALL_CHATTERBOX=1
INSTALL_QWEN3=1
INSTALL_COSYVOICE=1
INSTALL_WHISPER=1
INSTALL_RESEMBLE=0
INSTALL_F5=0
INSTALL_WHISPERX=0
INSTALL_CRISPERWHISPER=0

RUN_IMPORT_CHECKS=1
RUN_SMOKE_TESTS=0
DOWNLOAD_MODELS=1
ASSUME_YES=0

LOG_ROOT="${TTS_LOGS_DIR}/stack-installer"
LOG_FILE=""

usage() {
  cat <<EOF
HandAI TTS Lab Stack Installer v${VERSION}

Creates the engine stack expected by the HandAI TTS Lab Web UI:
  ${TTS_LAB}/tts-lab.sh synth chatterbox --text "..."
  ${TTS_LAB}/tts-lab.sh synth qwen3 --text "..." --x-vector-only
  ${TTS_LAB}/tts-lab.sh synth cosyvoice --text "..."

Usage:
  ./install-tts-lab-stack.sh [options]

Options:
  --yes                         Non-interactive best effort.
  --skip-system-deps            Do not apt-install ffmpeg/sox/git/espeak-ng/etc.
  --no-video-dl                 Do not clone/install HandAI Video Downloader.
  --no-engines                  Only create folders/launcher helpers; skip TTS engine envs.
  --only-video-dl               Only install/repair HandAI Video Downloader.
  --only-launchers              Only rewrite tts-lab.sh and wrapper scripts.
  --no-model-downloads          Install packages but do not pre-download Hugging Face models.
  --no-import-checks            Skip import checks after package installation.
  --run-smoke-tests             Generate short WAVs and run Whisper transcription after install.
  --with-resemble               Install Resemble Enhance.
  --with-f5-experimental        Install F5-TTS too. Known experimental/segfault risk on low VRAM.
  --with-whisperx               Install WhisperX.
  --with-crisperwhisper         Install CrisperWhisper.
  --skip-qwen3                  Do not install Qwen3-TTS.
  --skip-cosyvoice              Do not install CosyVoice.
  --skip-whisper                Do not install Faster-Whisper STT.
  --lab PATH                    Application root. Default: ${DEFAULT_TTS_LAB}
  --conda-root PATH             Conda install root. Default: ${DEFAULT_CONDA_ROOT}
  --video-dl-dir PATH           Video downloader directory. Default: ${DEFAULT_VIDEO_DL_DIR}
  --video-dl-repo URL           Video downloader repo. Default: ${DEFAULT_VIDEO_DL_REPO}
  -h, --help                    Show this help.

Environment overrides:
  TTS_LAB, CONDA_ROOT, VIDEO_DL_DIR, VIDEO_DL_REPO
  TTS_APP_DIR, TTS_DATA_DIR, TTS_MODEL_DIR, TTS_OUT, TTS_REF
  TTS_JOB_DIR, TTS_TAGGED_WORKSPACE_DIR, TTS_CONFIG_DIR
  PYTORCH_CUDA_INDEX, COSY_TORCH_INDEX
  VIDEO_DL_SKIP_SYSTEM_DEPS=1   Passed through to the video downloader installer.

Notes:
  - This installer is designed for Ubuntu/Linux + NVIDIA GPU + Conda.
  - Default engines: Chatterbox, Qwen3-TTS, CosyVoice, Faster-Whisper.
  - VRAM detection warns and prompts before skipping engines that may not fit.
  - Model caches are stored under ${TTS_MODEL_DIR}/.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) ASSUME_YES=1; shift ;;
    --skip-system-deps) INSTALL_SYSTEM_DEPS=0; shift ;;
    --no-video-dl) INSTALL_VIDEO_DL=0; shift ;;
    --no-engines) INSTALL_ENGINES=0; INSTALL_CHATTERBOX=0; INSTALL_QWEN3=0; INSTALL_COSYVOICE=0; INSTALL_WHISPER=0; shift ;;
    --only-video-dl) INSTALL_SYSTEM_DEPS=1; INSTALL_VIDEO_DL=1; INSTALL_ENGINES=0; INSTALL_CHATTERBOX=0; INSTALL_QWEN3=0; INSTALL_COSYVOICE=0; INSTALL_WHISPER=0; shift ;;
    --only-launchers) INSTALL_SYSTEM_DEPS=0; INSTALL_VIDEO_DL=0; INSTALL_ENGINES=0; RUN_IMPORT_CHECKS=0; DOWNLOAD_MODELS=0; shift ;;
    --no-model-downloads) DOWNLOAD_MODELS=0; shift ;;
    --no-import-checks) RUN_IMPORT_CHECKS=0; shift ;;
    --run-smoke-tests) RUN_SMOKE_TESTS=1; shift ;;
    --with-resemble) INSTALL_RESEMBLE=1; shift ;;
    --with-f5-experimental) INSTALL_F5=1; shift ;;
    --with-whisperx) INSTALL_WHISPERX=1; shift ;;
    --with-crisperwhisper) INSTALL_CRISPERWHISPER=1; shift ;;
    --skip-qwen3) INSTALL_QWEN3=0; shift ;;
    --skip-cosyvoice) INSTALL_COSYVOICE=0; shift ;;
    --skip-whisper) INSTALL_WHISPER=0; shift ;;
    --lab) TTS_LAB="$2"; shift 2 ;;
    --conda-root) CONDA_ROOT="$2"; shift 2 ;;
    --video-dl-dir) VIDEO_DL_DIR="$2"; shift 2 ;;
    --video-dl-repo) VIDEO_DL_REPO="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

# Re-derive layout after --lab may have changed
TTS_APP_DIR="${TTS_APP_DIR:-${TTS_LAB}/app}"
TTS_DATA_DIR="${TTS_DATA_DIR:-${TTS_LAB}/data}"
TTS_MODEL_DIR="${TTS_MODEL_DIR:-${TTS_LAB}/models}"
TTS_OUT="${TTS_OUT:-${TTS_DATA_DIR}/output}"
TTS_REF="${TTS_REF:-${TTS_DATA_DIR}/references}"
TTS_JOB_DIR="${TTS_JOB_DIR:-${TTS_OUT}/job_history}"
TTS_TAGGED_WORKSPACE_DIR="${TTS_TAGGED_WORKSPACE_DIR:-${TTS_DATA_DIR}/projects/tagged-script}"
TTS_CONFIG_DIR="${TTS_CONFIG_DIR:-${TTS_DATA_DIR}/config}"
TTS_BACKUP_DIR="${TTS_BACKUP_DIR:-${TTS_LAB}/backups}"
TTS_LOGS_DIR="${TTS_LOGS_DIR:-${TTS_LAB}/logs}"
TTS_TMP_DIR="${TTS_TMP_DIR:-${TTS_LAB}/tmp}"

LOG_ROOT="${TTS_LOGS_DIR}/stack-installer"
mkdir -p "$LOG_ROOT"
LOG_FILE="${LOG_ROOT}/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

trap 'echo "[ERROR] line $LINENO failed. Full log: $LOG_FILE" >&2' ERR

log() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\n[WARN] %s\n' "$*"; }
fail() { printf '\n[FAIL] %s\n' "$*" >&2; exit 1; }

run_step() {
  local name="$1"; shift
  log "$name"
  "$@"
}

confirm_or_warn() {
  local msg="$1"
  if [[ "$ASSUME_YES" == "1" ]]; then
    return 0
  fi
  echo "$msg"
  read -r -p "Continue? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || fail "Aborted by user."
}

preflight() {
  log "Preflight"
  echo "Version: ${VERSION}"
  echo "TTS_LAB: ${TTS_LAB}"
  echo "TTS_APP_DIR: ${TTS_APP_DIR}"
  echo "TTS_DATA_DIR: ${TTS_DATA_DIR}"
  echo "TTS_MODEL_DIR: ${TTS_MODEL_DIR}"
  echo "CONDA_ROOT: ${CONDA_ROOT}"
  echo "VIDEO_DL_DIR: ${VIDEO_DL_DIR}"
  echo "Log: ${LOG_FILE}"

  [[ "$(uname -s)" == "Linux" ]] || warn "This installer is intended for Linux. Continuing anyway."
  command -v bash >/dev/null || fail "bash is required."
  command -v python3 >/dev/null || warn "python3 was not found. System dependency install may fix this, but conda still needs shell tools."
  command -v git >/dev/null || warn "git was not found. System dependency install may fix this."
  command -v curl >/dev/null || command -v wget >/dev/null || warn "curl/wget was not found. Miniforge install may fail."

  if command -v nvidia-smi >/dev/null; then
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader || true
  else
    warn "nvidia-smi not found. CPU-only or non-NVIDIA systems are not the primary target for this installer."
  fi

  df -h "$HOME" || true
  mkdir -p "$TTS_LAB" "$LOG_ROOT"
}

detect_vram_mb() {
  if command -v nvidia-smi >/dev/null; then
    nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d '[:space:]' || true
  fi
}

plan_engines() {
  log "Planning engine installation based on hardware"
  local vram_mb=""
  vram_mb="$(detect_vram_mb)"
  if [[ -z "$vram_mb" ]]; then
    warn "Could not detect NVIDIA VRAM. Assuming minimum 6 GB for planning."
    vram_mb=6144
  fi
  local vram_gb=$(( (vram_mb + 512) / 1024 ))
  echo "Detected VRAM: ~${vram_gb} GB"

  local proposed_chatterbox=1 proposed_qwen3=1 proposed_cosy=1 proposed_whisper=1
  local notes=""

  if [[ "$vram_gb" -lt 8 ]]; then
    notes="${notes}
- Less than 8 GB VRAM detected. Qwen3 and CosyVoice may be slow or fail."
    if [[ "$ASSUME_YES" != "1" ]]; then
      proposed_qwen3=0
      proposed_cosy=0
    fi
  fi

  if [[ "$vram_gb" -lt 6 ]]; then
    notes="${notes}
- Less than 6 GB VRAM detected. Only CPU fallback or very small models are realistic."
    proposed_chatterbox=0
    proposed_whisper=0
  fi

  if [[ -n "$notes" ]]; then
    echo "$notes"
  fi

  echo "Default plan for ${vram_gb} GB VRAM:"
  echo "  Chatterbox: $([[ "$proposed_chatterbox" == "1" ]] && echo yes || echo no)"
  echo "  Qwen3:      $([[ "$proposed_qwen3" == "1" ]] && echo yes || echo no)"
  echo "  CosyVoice:  $([[ "$proposed_cosy" == "1" ]] && echo yes || echo no)"
  echo "  Whisper:    $([[ "$proposed_whisper" == "1" ]] && echo yes || echo no)"

  if [[ "$ASSUME_YES" != "1" ]]; then
    echo
    read -r -p "Accept this plan? [Y/n] " ans
    if [[ "${ans:-}" == "n" || "${ans:-}" == "N" ]]; then
      read -r -p "Install Chatterbox? [Y/n] " ans; [[ "${ans:-}" == "n" || "${ans:-}" == "N" ]] && INSTALL_CHATTERBOX=0 || INSTALL_CHATTERBOX=1
      read -r -p "Install Qwen3? [Y/n] " ans; [[ "${ans:-}" == "n" || "${ans:-}" == "N" ]] && INSTALL_QWEN3=0 || INSTALL_QWEN3=1
      read -r -p "Install CosyVoice? [Y/n] " ans; [[ "${ans:-}" == "n" || "${ans:-}" == "N" ]] && INSTALL_COSYVOICE=0 || INSTALL_COSYVOICE=1
      read -r -p "Install Faster-Whisper? [Y/n] " ans; [[ "${ans:-}" == "n" || "${ans:-}" == "N" ]] && INSTALL_WHISPER=0 || INSTALL_WHISPER=1
    else
      INSTALL_CHATTERBOX="$proposed_chatterbox"
      INSTALL_QWEN3="$proposed_qwen3"
      INSTALL_COSYVOICE="$proposed_cosy"
      INSTALL_WHISPER="$proposed_whisper"
    fi
  fi

  echo "Final engine plan:"
  echo "  Chatterbox: $([[ "$INSTALL_CHATTERBOX" == "1" ]] && echo yes || echo no)"
  echo "  Qwen3:      $([[ "$INSTALL_QWEN3" == "1" ]] && echo yes || echo no)"
  echo "  CosyVoice:  $([[ "$INSTALL_COSYVOICE" == "1" ]] && echo yes || echo no)"
  echo "  Whisper:    $([[ "$INSTALL_WHISPER" == "1" ]] && echo yes || echo no)"
}

install_system_deps() {
  [[ "$INSTALL_SYSTEM_DEPS" == "1" ]] || { log "Skipping system dependencies"; return 0; }
  log "Installing/checking system dependencies"
  if command -v apt-get >/dev/null; then
    local sudo_cmd=()
    if [[ "${EUID}" -ne 0 ]]; then
      command -v sudo >/dev/null || fail "sudo is required for apt-get system dependency installation. Re-run with --skip-system-deps if needed."
      sudo_cmd=(sudo)
    fi
    "${sudo_cmd[@]}" apt-get update
    "${sudo_cmd[@]}" apt-get install -y ca-certificates curl git ffmpeg sox libsox-dev espeak-ng git-lfs
    git lfs install --skip-repo || true
  else
    warn "apt-get not found. Please install git, ffmpeg, sox/libsox, espeak-ng, curl, and git-lfs manually."
  fi
}

install_conda() {
  log "Installing/checking Conda"
  if [[ -x "${CONDA_ROOT}/bin/conda" ]]; then
    echo "Conda already exists: ${CONDA_ROOT}/bin/conda"
    return 0
  fi

  confirm_or_warn "Conda was not found at ${CONDA_ROOT}. The installer can install Miniforge there."
  mkdir -p "$(dirname "$CONDA_ROOT")"
  local installer="/tmp/miniforge-installer-$$.sh"
  local url="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
  if command -v curl >/dev/null; then
    curl -LfsS "$url" -o "$installer"
  else
    wget -O "$installer" "$url"
  fi
  bash "$installer" -b -p "$CONDA_ROOT"
  rm -f "$installer"
}

conda_shell() {
  # shellcheck disable=SC1090
  source "${CONDA_ROOT}/etc/profile.d/conda.sh"
}

env_exists() {
  local env_name="$1"
  "${CONDA_ROOT}/bin/conda" env list | awk '{print $1}' | grep -qx "$env_name"
}

create_env() {
  local env_name="$1"
  local pyver="$2"
  conda_shell
  if env_exists "$env_name"; then
    echo "Conda env exists: ${env_name}"
  else
    conda create -n "$env_name" -y "python=${pyver}"
  fi
}

pip_in_env() {
  local env_name="$1"; shift
  "${CONDA_ROOT}/envs/${env_name}/bin/python" -m pip "$@"
}

python_in_env() {
  local env_name="$1"; shift
  "${CONDA_ROOT}/envs/${env_name}/bin/python" "$@"
}

install_pytorch_in_env() {
  local env_name="$1"
  local index_url="$2"
  log "Installing PyTorch in ${env_name} from ${index_url}"
  pip_in_env "$env_name" install --upgrade pip setuptools wheel
  pip_in_env "$env_name" install "torch==2.6.0" "torchaudio==2.6.0" --index-url "$index_url"
}

create_lab_folders() {
  log "Creating TTS lab folders"
  mkdir -p \
    "${TTS_DATA_DIR}/scripts" \
    "${TTS_REF}" \
    "${TTS_REF}/profiles" \
    "${TTS_OUT}" \
    "${TTS_JOB_DIR}" \
    "${TTS_OUT}/audio_lab" \
    "${TTS_OUT}/video_intake/source_media/uploads" \
    "${TTS_OUT}/video_intake/source_media/url_imports" \
    "${TTS_OUT}/video_intake/extracted_audio" \
    "${TTS_OUT}/resemble_enhance" \
    "${TTS_DATA_DIR}/resemble_uploads" \
    "${TTS_DATA_DIR}/stt_uploads" \
    "${TTS_CONFIG_DIR}" \
    "${TTS_TAGGED_WORKSPACE_DIR}/scripts" \
    "${TTS_TAGGED_WORKSPACE_DIR}/casts" \
    "${TTS_TAGGED_WORKSPACE_DIR}/projects" \
    "${TTS_MODEL_DIR}/huggingface" \
    "${TTS_MODEL_DIR}/torch" \
    "${TTS_LAB}/engines" \
    "${TTS_TMP_DIR}" \
    "${TTS_BACKUP_DIR}" \
    "${TTS_LOGS_DIR}/ui-diagnostics" \
    "${TTS_LOGS_DIR}/model-installs" \
    "${TTS_LOGS_DIR}/stack-installer"

  if [[ ! -f "${TTS_REF}/ref_text.txt" ]]; then
    cat > "${TTS_REF}/ref_text.txt" <<'EOF'
This is my reference voice sample for cloning.
EOF
  fi
}

write_launcher_scripts() {
  log "Writing launcher and wrapper scripts"
  mkdir -p "${TTS_DATA_DIR}/scripts"

  cat > "${TTS_LAB}/tts-lab.sh" <<'BASH_LAUNCHER'
#!/usr/bin/env bash
# Unified launcher for local TTS voice-cloning engines.
set -euo pipefail

LAB="${TTS_LAB:-$HOME/handai-tts-lab}"
APP_DIR="${TTS_APP_DIR:-${LAB}/app}"
DATA_DIR="${TTS_DATA_DIR:-${LAB}/data}"
MODEL_DIR="${TTS_MODEL_DIR:-${LAB}/models}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
CONDA="${CONDA_ROOT}/etc/profile.d/conda.sh"
REF="${TTS_REF:-${DATA_DIR}/references/voice_ref.wav}"
REF_TEXT="${TTS_REF_TEXT:-${DATA_DIR}/references/ref_text.txt}"
OUT="${TTS_OUT:-${DATA_DIR}/output}"
SCRIPTS="${DATA_DIR}/scripts"
VIDEO_DL_DIR="${VIDEO_DL_DIR:-$HOME/video-dl}"
VIDEO_DL_BIN="${VIDEO_DL_BIN:-${VIDEO_DL_DIR}/video-dl}"

usage() {
  cat <<'EOF'
Usage: tts-lab.sh <command> [args]

Commands:
  synth <engine> --text "..." [--ref PATH] [--ref-text "..."] [--out PATH] [--language English]
      Engines: chatterbox | qwen3 | cosyvoice | f5
      Qwen3 supports --x-vector-only.

  synth-chatterbox-batch --manifest PATH
      Render many Chatterbox-Turbo utterances from a JSON manifest.
      Loads the model once and writes each output file separately.

  ui <engine>
      Launch a web UI where available.
      Engines: chatterbox | qwen3 | f5

  video-dl URL OUT_DIR
      Run the configured HandAI Video Downloader.

  status
      Show launcher, engine, and helper status.

  test [engine]
      Run a short synthesis test. If engine is omitted, tests chatterbox qwen3 cosyvoice, and f5 if installed.

  env <engine>
      Print conda activate command for an engine.

Examples:
  tts-lab.sh synth chatterbox --text "Hello from the executive office."
  tts-lab.sh synth qwen3 --text "Status update." --x-vector-only
  tts-lab.sh synth cosyvoice --text "Proceed with the archive step."
  tts-lab.sh video-dl 'https://example.invalid/video' /tmp/video-test
EOF
}

activate_env() {
  [[ -f "$CONDA" ]] || { echo "Conda hook not found: $CONDA" >&2; exit 1; }
  # shellcheck disable=SC1090
  source "$CONDA"
  case "$1" in
    chatterbox) conda activate tts-chatterbox ;;
    qwen3)      conda activate tts-qwen3 ;;
    cosyvoice)  conda activate tts-cosyvoice ;;
    f5)         conda activate tts-f5 ;;
    whisper)    conda activate tts-whisper ;;
    whisperx)   conda activate tts-whisperx ;;
    crisperwhisper) conda activate tts-crisperwhisper ;;
    *) echo "Unknown engine: $1" >&2; exit 1 ;;
  esac
  export TMPDIR="${LAB}/tmp"
  export HF_HOME="${MODEL_DIR}/huggingface"
  export TORCH_HOME="${MODEL_DIR}/torch"
  mkdir -p "$TMPDIR" "$HF_HOME" "$TORCH_HOME" "$OUT"
}

cmd_synth() {
  local engine="$1"; shift
  local text="" ref="$REF" ref_text="" out="" xvector="" language="English" temperature="" repetition_penalty="" top_p="" top_k="" seed="" norm_loudness="1"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --text) text="$2"; shift 2 ;;
      --ref) ref="$2"; shift 2 ;;
      --ref-text) ref_text="$2"; shift 2 ;;
      --out) out="$2"; shift 2 ;;
      --language) language="$2"; shift 2 ;;
      --temperature) temperature="$2"; shift 2 ;;
      --repetition-penalty) repetition_penalty="$2"; shift 2 ;;
      --top-p) top_p="$2"; shift 2 ;;
      --top-k) top_k="$2"; shift 2 ;;
      --seed) seed="$2"; shift 2 ;;
      --no-norm-loudness) norm_loudness="0"; shift ;;
      --x-vector-only) xvector="1"; shift ;;
      *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
  done

  [[ -n "$text" ]] || { echo "--text is required" >&2; exit 1; }
  [[ -f "$ref" ]] || { echo "Reference audio not found: $ref" >&2; exit 1; }

  if [[ -z "$out" ]]; then
    ts="$(date +%Y%m%d_%H%M%S)"
    out="${OUT}/${engine}_${ts}.wav"
  fi

  activate_env "$engine"

  case "$engine" in
    chatterbox)
      args=(--text "$text" --ref "$ref" --out "$out")
      [[ -n "$temperature" ]] && args+=(--temperature "$temperature")
      [[ -n "$repetition_penalty" ]] && args+=(--repetition-penalty "$repetition_penalty")
      [[ -n "$top_p" ]] && args+=(--top-p "$top_p")
      [[ -n "$top_k" ]] && args+=(--top-k "$top_k")
      [[ -n "$seed" ]] && args+=(--seed "$seed")
      [[ "$norm_loudness" == "0" ]] && args+=(--no-norm-loudness)
      python "$SCRIPTS/synth_chatterbox.py" "${args[@]}"
      ;;
    qwen3)
      args=(--text "$text" --ref "$ref" --out "$out" --language "$language")
      if [[ -n "$ref_text" ]]; then
        args+=(--ref-text "$ref_text")
      else
        xvector="1"
      fi
      [[ -n "$xvector" ]] && args+=(--x-vector-only)
      python "$SCRIPTS/synth_qwen3.py" "${args[@]}"
      ;;
    cosyvoice)
      if [[ -z "$ref_text" && -f "$REF_TEXT" ]]; then
        ref_text="$(tr -d '\n' < "$REF_TEXT")"
      fi
      prompt="You are a helpful assistant.<|endofprompt|>${ref_text:-This is my reference voice sample for cloning.}"
      PYTHONPATH="${APP_DIR}/engines/cosyvoice/CosyVoice:${APP_DIR}/engines/cosyvoice/CosyVoice/third_party/Matcha-TTS:${PYTHONPATH:-}"
      export PYTHONPATH
      if ! python "$SCRIPTS/synth_cosyvoice.py" --text "$text" --ref "$ref" --prompt "$prompt" --out "$out"; then
        rc=$?
        if [[ -s "$out" ]]; then
          echo "Warning: CosyVoice exited non-zero (${rc}) after writing output: $out" >&2
          echo "Treating this as a successful render with a teardown warning." >&2
        else
          exit "$rc"
        fi
      fi
      ;;
    f5)
      if [[ -z "$ref_text" && -f "$REF_TEXT" ]]; then
        ref_text="$(tr -d '\n' < "$REF_TEXT")"
      fi
      [[ -n "$ref_text" ]] || { echo "F5 requires --ref-text or ${REF_TEXT}" >&2; exit 1; }
      python "$SCRIPTS/synth_f5.py" --text "$text" --ref "$ref" --ref-text "$ref_text" --out "$out"
      ;;
    *) echo "Unknown engine: $engine" >&2; exit 1 ;;
  esac
}

cmd_synth_chatterbox_batch() {
  local manifest=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --manifest) manifest="$2"; shift 2 ;;
      *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
  done
  [[ -n "$manifest" ]] || { echo "--manifest is required" >&2; exit 1; }
  [[ -f "$manifest" ]] || { echo "Manifest not found: $manifest" >&2; exit 1; }
  activate_env chatterbox
  python "${SCRIPTS}/synth_chatterbox_batch.py" --manifest "$manifest" --device cuda
}

cmd_ui() {
  local engine="$1"
  activate_env "$engine"
  case "$engine" in
    chatterbox)
      python -c "import chatterbox, os; from pathlib import Path; p=Path(chatterbox.__file__).parent.parent; os.chdir(p); exec(open('gradio_tts_turbo_app.py').read())"
      ;;
    qwen3)
      qwen-tts-demo Qwen/Qwen3-TTS-12Hz-0.6B-Base --ip 127.0.0.1 --port 7861
      ;;
    f5)
      f5-tts_infer-gradio
      ;;
    *)
      echo "No UI launcher for $engine. Use synth command or the engine's own docs." >&2
      exit 1
      ;;
  esac
}

cmd_video_dl() {
  local url="$1" out_dir="$2"
  if [[ -n "${TTS_VIDEO_DL_CMD:-}" ]]; then
    local cmd="${TTS_VIDEO_DL_CMD//\{url\}/$url}"
    cmd="${cmd//\{out\}/$out_dir}"
    bash -lc "$cmd"
    return $?
  fi
  [[ -x "$VIDEO_DL_BIN" ]] || { echo "video-dl not executable: $VIDEO_DL_BIN" >&2; exit 1; }
  "$VIDEO_DL_BIN" "$url" "$out_dir"
}

cmd_status() {
  echo "TTS Lab launcher status"
  echo "LAB=$LAB"
  echo "APP_DIR=$APP_DIR"
  echo "DATA_DIR=$DATA_DIR"
  echo "MODEL_DIR=$MODEL_DIR"
  echo "CONDA_ROOT=$CONDA_ROOT"
  echo "REF=$REF"
  echo "OUT=$OUT"
  echo "VIDEO_DL_BIN=$VIDEO_DL_BIN"
  [[ -x "$VIDEO_DL_BIN" ]] && echo "video-dl: OK" || echo "video-dl: missing/not executable"
  for e in chatterbox qwen3 cosyvoice f5 whisper whisperx crisperwhisper; do
    if [[ -d "${CONDA_ROOT}/envs/tts-${e}" ]]; then
      echo "env tts-${e}: present"
    else
      echo "env tts-${e}: missing"
    fi
  done
}

cmd_test() {
  local only="${1:-}"
  local text="This is a quick voice cloning test on my local GPU."
  echo "Reference: $REF"
  echo "Test text: $text"
  mkdir -p "$OUT"
  [[ -f "$REF" ]] || { echo "Reference audio not found: $REF" >&2; exit 1; }

  local engines=(chatterbox qwen3 cosyvoice)
  [[ -d "${CONDA_ROOT}/envs/tts-f5" ]] && engines+=(f5)
  if [[ -n "$only" ]]; then engines=("$only"); fi

  for engine in "${engines[@]}"; do
    echo "=== Testing $engine ==="
    if [[ "$engine" == "qwen3" ]]; then
      cmd_synth "$engine" --text "$text" --out "${OUT}/test_${engine}.wav" --x-vector-only
    else
      cmd_synth "$engine" --text "$text" --out "${OUT}/test_${engine}.wav"
    fi
  done
  echo "Done. Outputs in ${OUT}/test_*.wav"
}

cmd_env() {
  echo "source ${CONDA} && conda activate tts-$1"
}

main() {
  [[ $# -ge 1 ]] || { usage; exit 1; }
  case "$1" in
    synth) shift; [[ $# -ge 1 ]] || { usage; exit 1; }; cmd_synth "$@" ;;
    synth-chatterbox-batch) shift; cmd_synth_chatterbox_batch "$@" ;;
    ui) shift; [[ $# -eq 1 ]] || { usage; exit 1; }; cmd_ui "$1" ;;
    video-dl) shift; [[ $# -eq 2 ]] || { usage; exit 1; }; cmd_video_dl "$1" "$2" ;;
    status) shift; cmd_status ;;
    test) shift; cmd_test "${1:-}" ;;
    env) shift; [[ $# -eq 1 ]] || { usage; exit 1; }; cmd_env "$1" ;;
    -h|--help|help) usage ;;
    *) usage; exit 1 ;;
  esac
}

main "$@"
BASH_LAUNCHER
  # Bake the actual install paths into the launcher defaults so the generated
  # tts-lab.sh works without manually exporting TTS_LAB/CONDA_ROOT on this machine.
  sed -i "s|\${TTS_LAB:-\$HOME/handai-tts-lab}|\${TTS_LAB:-${TTS_LAB}}|g; s|\${CONDA_ROOT:-\$HOME/miniconda3}|\${CONDA_ROOT:-${CONDA_ROOT}}|g" "${TTS_LAB}/tts-lab.sh"
  chmod +x "${TTS_LAB}/tts-lab.sh"

  cat > "${TTS_DATA_DIR}/scripts/synth_chatterbox.py" <<'PY'
#!/usr/bin/env python3
"""Generate speech with Chatterbox-Turbo using explicit sampling controls."""
import argparse
import json
import random
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS


class _DummyImplicitWatermarker:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


# On some platforms resemble-perth exposes PerthImplicitWatermarker as None.
import chatterbox.tts_turbo as _cb_mod
if getattr(_cb_mod, "perth", None) is not None:
    _cb_mod.perth.PerthImplicitWatermarker = _DummyImplicitWatermarker


def main() -> None:
    p = argparse.ArgumentParser(description="Chatterbox-Turbo voice clone")
    p.add_argument("--text", required=True, help="Text to synthesize")
    p.add_argument("--ref", required=True, help="Reference WAV for voice cloning")
    p.add_argument("--out", required=True, help="Output WAV path")
    p.add_argument("--device", default="cuda", help="cuda or cpu")
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--repetition-penalty", type=float, default=1.2)
    p.add_argument("--top-p", type=float, default=0.95)
    p.add_argument("--top-k", type=int, default=1000)
    p.add_argument("--seed", type=int, default=None, help="Optional reproducible sampling seed")
    p.add_argument("--no-norm-loudness", dest="norm_loudness", action="store_false")
    p.set_defaults(norm_loudness=True)
    args = p.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed % (2**32))
        torch.manual_seed(args.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(args.seed)

    model = ChatterboxTurboTTS.from_pretrained(device=args.device)

    class _NoWatermark:
        def apply_watermark(self, wav, sample_rate=None):
            return wav

    model.watermarker = _NoWatermark()

    options = {
        "temperature": max(0.05, min(2.0, args.temperature)),
        "repetition_penalty": max(0.5, min(3.0, args.repetition_penalty)),
        "top_p": max(0.05, min(1.0, args.top_p)),
        "top_k": max(1, min(5000, args.top_k)),
        "seed": args.seed,
        "norm_loudness": bool(args.norm_loudness),
    }
    print("Chatterbox-Turbo options: " + json.dumps(options, sort_keys=True), flush=True)
    wav = model.generate(
        args.text,
        audio_prompt_path=args.ref,
        temperature=options["temperature"],
        repetition_penalty=options["repetition_penalty"],
        top_p=options["top_p"],
        top_k=options["top_k"],
        norm_loudness=options["norm_loudness"],
    )
    sf.write(str(out), wav.squeeze().cpu().numpy(), model.sr)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
PY
  chmod +x "${TTS_DATA_DIR}/scripts/synth_chatterbox.py"


  cat > "${TTS_DATA_DIR}/scripts/synth_chatterbox_batch.py" <<'PY'
#!/usr/bin/env python3
"""Batch Chatterbox-Turbo renderer.

Loads the model once and renders many utterances from a JSON manifest.
Manifest format (stdin or --manifest path):
[
  {
    "text": "...",
    "ref": "/path/to/ref.wav",
    "out": "/path/to/out.wav",
    "ref_text": "...",
    "temperature": 0.8,
    "repetition_penalty": 1.2,
    "top_p": 0.95,
    "top_k": 1000,
    "seed": null,
    "norm_loudness": true
  },
  ...
]
"""
import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS


class _DummyImplicitWatermarker:
    def apply_watermark(self, wav, sample_rate=None):
        return wav


# On some platforms resemble-perth exposes PerthImplicitWatermarker as None.
import chatterbox.tts_turbo as _cb_mod
if getattr(_cb_mod, "perth", None) is not None:
    _cb_mod.perth.PerthImplicitWatermarker = _DummyImplicitWatermarker


def set_seed(seed: int | None) -> None:
    if seed is None:
        return
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def main() -> None:
    p = argparse.ArgumentParser(description="Batch Chatterbox-Turbo voice renderer")
    p.add_argument("--manifest", required=True, help="Path to JSON manifest file")
    p.add_argument("--device", default="cuda", help="cuda or cpu")
    p.add_argument("--progress-every", type=int, default=1, help="Print progress every N items")
    args = p.parse_args()

    manifest_path = Path(args.manifest)
    with open(manifest_path) as f:
        manifest = json.load(f)

    if not isinstance(manifest, list) or not manifest:
        print("Manifest must be a non-empty JSON array.", file=sys.stderr)
        sys.exit(1)

    print(f"Batch Chatterbox-Turbo: {len(manifest)} items on {args.device}", flush=True)

    # Load model once.
    print("Loading Chatterbox-Turbo model...", flush=True)
    model = ChatterboxTurboTTS.from_pretrained(device=args.device)
    model.watermarker = _DummyImplicitWatermarker()
    print("Model loaded.", flush=True)

    ok = 0
    failed = 0
    for i, item in enumerate(manifest, start=1):
        text = str(item.get("text") or "").strip()
        ref = item.get("ref")
        out = item.get("out")
        if not text or not ref or not out:
            print(f"[{i}/{len(manifest)}] SKIP missing text/ref/out", flush=True)
            failed += 1
            continue

        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        options = {
            "temperature": max(0.05, min(2.0, float(item.get("temperature", 0.8)))),
            "repetition_penalty": max(0.5, min(3.0, float(item.get("repetition_penalty", 1.2)))),
            "top_p": max(0.05, min(1.0, float(item.get("top_p", 0.95)))),
            "top_k": max(1, min(5000, int(item.get("top_k", 1000)))),
            "seed": item.get("seed"),
            "norm_loudness": bool(item.get("norm_loudness", True)),
        }

        set_seed(options["seed"])

        try:
            wav = model.generate(
                text,
                audio_prompt_path=ref,
                temperature=options["temperature"],
                repetition_penalty=options["repetition_penalty"],
                top_p=options["top_p"],
                top_k=options["top_k"],
                norm_loudness=options["norm_loudness"],
            )
            sf.write(str(out_path), wav.squeeze().cpu().numpy(), model.sr)
            ok += 1
            print(f"__CHATTERBOX_BATCH_PROGRESS__ {i} {len(manifest)}", flush=True)
            if i % max(1, args.progress_every) == 0 or i == len(manifest):
                print(f"[{i}/{len(manifest)}] Wrote {out_path}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"[{i}/{len(manifest)}] ERROR {out}: {exc}", file=sys.stderr, flush=True)

    print(f"Batch done: {ok} ok, {failed} failed, {len(manifest)} total", flush=True)


if __name__ == "__main__":
    main()

PY
  chmod +x "${TTS_DATA_DIR}/scripts/synth_chatterbox_batch.py"

  cat > "${TTS_DATA_DIR}/scripts/synth_qwen3.py" <<'PY'
#!/usr/bin/env python3
"""Generate speech with Qwen3-TTS 0.6B Base voice clone."""
import argparse
from pathlib import Path

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


def main() -> None:
    p = argparse.ArgumentParser(description="Qwen3-TTS 0.6B voice clone")
    p.add_argument("--text", required=True, help="Text to synthesize")
    p.add_argument("--ref", required=True, help="Reference audio WAV")
    p.add_argument("--ref-text", default="", help="Transcript of reference audio")
    p.add_argument("--out", required=True, help="Output WAV path")
    p.add_argument("--language", default="English")
    p.add_argument("--x-vector-only", action="store_true", help="Skip ref_text requirement")
    args = p.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    model = Qwen3TTSModel.from_pretrained(
        "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        device_map="cuda:0",
        dtype=torch.bfloat16,
    )

    x_vector_only = args.x_vector_only or not bool(args.ref_text.strip())
    if x_vector_only and not args.x_vector_only:
        print("No --ref-text supplied; using Qwen3 x-vector-only mode.")

    kwargs = {
        "text": args.text,
        "language": args.language,
        "ref_audio": args.ref,
        "x_vector_only_mode": x_vector_only,
    }
    if args.ref_text:
        kwargs["ref_text"] = args.ref_text

    wavs, sr = model.generate_voice_clone(**kwargs)
    sf.write(str(out), wavs[0], sr)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
PY
  chmod +x "${TTS_DATA_DIR}/scripts/synth_qwen3.py"

  cat > "${TTS_DATA_DIR}/scripts/synth_cosyvoice.py" <<'PY'
#!/usr/bin/env python3
"""Generate speech with CosyVoice 3 zero-shot cloning.

This wrapper deliberately avoids torchaudio.save because some local stacks have
shown native-library segfaults around Torch/Torchaudio/ONNXRuntime teardown.
"""
import argparse
import os
import sys
import wave
from pathlib import Path

import numpy as np

LAB = Path(os.environ.get("TTS_LAB", str(Path.home() / "handai-tts-lab")))
APP_DIR = Path(os.environ.get("TTS_APP_DIR", str(LAB / "app")))
COSY_ROOT = Path(os.environ.get("COSYVOICE_ROOT", str(APP_DIR / "engines" / "cosyvoice" / "CosyVoice")))
sys.path.insert(0, str(COSY_ROOT))
sys.path.insert(0, str(COSY_ROOT / "third_party" / "Matcha-TTS"))

from cosyvoice.cli.cosyvoice import AutoModel  # noqa: E402

MODEL_DIR = Path(os.environ.get("COSYVOICE_MODEL_DIR", str(COSY_ROOT / "pretrained_models" / "Fun-CosyVoice3-0.5B")))


def write_pcm16_wav(path: Path, audio, sample_rate: int) -> None:
    """Write mono/stereo float tensor/array to PCM16 WAV without torchaudio."""
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    arr = np.asarray(audio)
    arr = np.squeeze(arr)
    if arr.ndim == 0:
        raise RuntimeError("CosyVoice returned scalar audio, not a waveform")
    if arr.ndim == 1:
        channels = 1
    elif arr.ndim == 2:
        if arr.shape[0] <= 8 and arr.shape[1] > arr.shape[0]:
            arr = arr.T
        channels = arr.shape[1]
    else:
        raise RuntimeError(f"Unsupported audio shape: {arr.shape}")
    arr = np.clip(arr.astype(np.float32), -1.0, 1.0)
    pcm = (arr * 32767.0).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.tobytes())


def main() -> None:
    p = argparse.ArgumentParser(description="CosyVoice 3 zero-shot voice clone")
    p.add_argument("--text", required=True, help="Text to synthesize")
    p.add_argument("--ref", required=True, help="Reference WAV")
    p.add_argument(
        "--prompt",
        default="You are a helpful assistant.<|endofprompt|>This is my reference voice sample for cloning.",
        help="Prompt prefix + transcript spoken in the reference clip",
    )
    p.add_argument("--out", required=True, help="Output WAV path")
    args = p.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    cosyvoice = AutoModel(model_dir=str(MODEL_DIR))
    chunks = list(cosyvoice.inference_zero_shot(args.text, args.prompt, args.ref, stream=False))
    if not chunks:
        raise RuntimeError("CosyVoice returned no audio")

    write_pcm16_wav(out, chunks[0]["tts_speech"], cosyvoice.sample_rate)
    print(f"Wrote {out}", flush=True)


if __name__ == "__main__":
    main()
PY
  chmod +x "${TTS_DATA_DIR}/scripts/synth_cosyvoice.py"

  cat > "${TTS_DATA_DIR}/scripts/synth_f5.py" <<'PY'
#!/usr/bin/env python3
"""Generate speech with F5-TTS zero-shot cloning. Experimental."""
import argparse
import subprocess
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="F5-TTS voice clone")
    p.add_argument("--text", required=True, help="Text to synthesize")
    p.add_argument("--ref", required=True, help="Reference WAV")
    p.add_argument("--ref-text", required=True, help="Exact transcript spoken in the reference clip")
    p.add_argument("--out", required=True, help="Output WAV path")
    args = p.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "f5-tts_infer-cli",
        "-m", "F5TTS_v1_Base",
        "-r", args.ref,
        "-s", args.ref_text,
        "-t", args.text,
        "-o", str(out.parent),
        "-w", out.name,
    ]
    subprocess.run(cmd, check=True)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
PY
  chmod +x "${TTS_DATA_DIR}/scripts/synth_f5.py"
}

install_chatterbox() {
  [[ "$INSTALL_ENGINES" == "1" && "$INSTALL_CHATTERBOX" == "1" ]] || return 0
  log "Installing Chatterbox-Turbo"
  create_env tts-chatterbox 3.11
  install_pytorch_in_env tts-chatterbox "$PYTORCH_CUDA_INDEX"
  pip_in_env tts-chatterbox install chatterbox-tts soundfile
  if [[ "$RUN_IMPORT_CHECKS" == "1" ]]; then
    python_in_env tts-chatterbox - <<'PY'
from chatterbox.tts_turbo import ChatterboxTurboTTS
print("chatterbox import ok")
PY
  fi
}

download_chatterbox_model() {
  [[ "$INSTALL_CHATTERBOX" == "1" && "$DOWNLOAD_MODELS" == "1" ]] || return 0
  log "Pre-downloading Chatterbox-Turbo model"
  HF_HOME="${TTS_MODEL_DIR}/huggingface" TORCH_HOME="${TTS_MODEL_DIR}/torch" \
    python_in_env tts-chatterbox - <<'PY' || warn "Chatterbox model pre-download failed; will download on first use."
from chatterbox.tts_turbo import ChatterboxTurboTTS
try:
    m = ChatterboxTurboTTS.from_pretrained(device="cuda")
    print("chatterbox model cached")
except Exception as e:
    print(f"chatterbox model pre-download skipped: {e}")
PY
}

install_whisper() {
  [[ "$INSTALL_ENGINES" == "1" && "$INSTALL_WHISPER" == "1" ]] || return 0
  log "Installing Faster-Whisper STT"
  create_env tts-whisper 3.11
  pip_in_env tts-whisper install --upgrade pip setuptools wheel
  pip_in_env tts-whisper install -U faster-whisper "huggingface_hub[cli]"
  if [[ "$RUN_IMPORT_CHECKS" == "1" ]]; then
    python_in_env tts-whisper - <<'PY'
import faster_whisper
print("faster-whisper import ok")
PY
  fi
}

download_whisper_model() {
  [[ "$INSTALL_WHISPER" == "1" && "$DOWNLOAD_MODELS" == "1" ]] || return 0
  log "Pre-downloading Faster-Whisper base model"
  HF_HOME="${TTS_MODEL_DIR}/huggingface" TORCH_HOME="${TTS_MODEL_DIR}/torch" \
    python_in_env tts-whisper - <<'PY'
from faster_whisper import WhisperModel
m = WhisperModel("base", device="cuda", compute_type="float16")
print("faster-whisper base model cached")
PY
}

install_qwen3() {
  [[ "$INSTALL_ENGINES" == "1" && "$INSTALL_QWEN3" == "1" ]] || return 0
  log "Installing Qwen3-TTS 0.6B"
  create_env tts-qwen3 3.12
  install_pytorch_in_env tts-qwen3 "$PYTORCH_CUDA_INDEX"
  pip_in_env tts-qwen3 install -U qwen-tts soundfile
  # qwen-tts pulls transformers 4.x which requires huggingface-hub<1.0, but
  # huggingface_hub[cli] -U would re-upgrade it. Pin it <1.0 before the CLI.
  pip_in_env tts-qwen3 install --no-deps "huggingface-hub<1.0"
  if [[ "$DOWNLOAD_MODELS" == "1" ]]; then
    pip_in_env tts-qwen3 install -U "huggingface_hub[cli]<1.0"
    HF_HOME="${TTS_MODEL_DIR}/huggingface" TORCH_HOME="${TTS_MODEL_DIR}/torch" \
      "${CONDA_ROOT}/envs/tts-qwen3/bin/huggingface-cli" download Qwen/Qwen3-TTS-Tokenizer-12Hz || true
    HF_HOME="${TTS_MODEL_DIR}/huggingface" TORCH_HOME="${TTS_MODEL_DIR}/torch" \
      "${CONDA_ROOT}/envs/tts-qwen3/bin/huggingface-cli" download Qwen/Qwen3-TTS-12Hz-0.6B-Base || true
  fi
  # Final safety: any -U install above may have bumped huggingface-hub back to 1.x
  pip_in_env tts-qwen3 install --no-deps "huggingface-hub<1.0"
  if [[ "$RUN_IMPORT_CHECKS" == "1" ]]; then
    python_in_env tts-qwen3 - <<'PY'
from qwen_tts import Qwen3TTSModel
print("qwen3 import ok")
PY
  fi
}

install_cosyvoice() {
  [[ "$INSTALL_ENGINES" == "1" && "$INSTALL_COSYVOICE" == "1" ]] || return 0
  log "Installing CosyVoice 3"
  create_env tts-cosyvoice 3.10
  pip_in_env tts-cosyvoice install --upgrade pip setuptools wheel
  pip_in_env tts-cosyvoice install "torch==2.3.1" "torchaudio==2.3.1" --index-url "$COSY_TORCH_INDEX"

  mkdir -p "${TTS_LAB}/engines/cosyvoice"
  if [[ -d "${TTS_LAB}/engines/cosyvoice/CosyVoice/.git" ]]; then
    git -C "${TTS_LAB}/engines/cosyvoice/CosyVoice" pull --ff-only || warn "CosyVoice git pull failed; continuing with existing checkout."
    git -C "${TTS_LAB}/engines/cosyvoice/CosyVoice" submodule update --init --recursive || true
  else
    rm -rf "${TTS_LAB}/engines/cosyvoice/CosyVoice"
    git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git "${TTS_LAB}/engines/cosyvoice/CosyVoice"
  fi

  local req="${TTS_LAB}/engines/cosyvoice/CosyVoice/requirements.txt"
  local filtered="${TTS_LAB}/engines/cosyvoice/requirements-inference-filtered.txt"
  if [[ -f "$req" ]]; then
    grep -v -E 'deepspeed|tensorrt|openai-whisper' "$req" > "$filtered"
    pip_in_env tts-cosyvoice install -r "$filtered" || warn "CosyVoice filtered requirements had failures; installing known inference dependencies next."
  fi
  pip_in_env tts-cosyvoice install pyarrow pyworld lightning fastapi uvicorn modelscope "huggingface_hub[cli]" soundfile librosa openai-whisper

  if [[ "$DOWNLOAD_MODELS" == "1" ]]; then
    (cd "${TTS_LAB}/engines/cosyvoice/CosyVoice" && \
      HF_HOME="${TTS_MODEL_DIR}/huggingface" TORCH_HOME="${TTS_MODEL_DIR}/torch" \
      "${CONDA_ROOT}/envs/tts-cosyvoice/bin/python" - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='pretrained_models/Fun-CosyVoice3-0.5B')
PY
    )
  fi
  if [[ "$RUN_IMPORT_CHECKS" == "1" ]]; then
    PYTHONPATH="${TTS_LAB}/engines/cosyvoice/CosyVoice:${TTS_LAB}/engines/cosyvoice/CosyVoice/third_party/Matcha-TTS" \
      python_in_env tts-cosyvoice - <<'PY'
from cosyvoice.cli.cosyvoice import AutoModel
print("cosyvoice import ok")
PY
  fi
}

install_f5_experimental() {
  [[ "$INSTALL_ENGINES" == "1" && "$INSTALL_F5" == "1" ]] || return 0
  log "Installing F5-TTS experimental"
  create_env tts-f5 3.11
  install_pytorch_in_env tts-f5 "$PYTORCH_CUDA_INDEX"
  pip_in_env tts-f5 install f5-tts numpy soundfile pyyaml sympy transformers accelerate
  if [[ "$RUN_IMPORT_CHECKS" == "1" ]]; then
    python_in_env tts-f5 - <<'PY'
import torch
print("f5 torch", torch.__version__, torch.cuda.is_available())
PY
  fi
  warn "F5 installed as experimental. The original RTX 2060 session hit SIGSEGV during generation."
}

install_resemble_enhance() {
  [[ "$INSTALL_ENGINES" == "1" && "$INSTALL_RESEMBLE" == "1" ]] || return 0
  log "Resemble Enhance selected; installer script will be created by webui/install.sh."
}

install_whisperx() {
  [[ "$INSTALL_ENGINES" == "1" && "$INSTALL_WHISPERX" == "1" ]] || return 0
  log "Installing WhisperX"
  create_env tts-whisperx 3.11
  pip_in_env tts-whisperx install --upgrade pip setuptools wheel
  pip_in_env tts-whisperx install -U faster-whisper whisperx
  if [[ "$RUN_IMPORT_CHECKS" == "1" ]]; then
    python_in_env tts-whisperx - <<'PY'
import whisperx
print("whisperx import ok")
PY
  fi
}

install_crisperwhisper() {
  [[ "$INSTALL_ENGINES" == "1" && "$INSTALL_CRISPERWHISPER" == "1" ]] || return 0
  log "Installing CrisperWhisper"
  create_env tts-crisperwhisper 3.11
  pip_in_env tts-crisperwhisper install --upgrade pip setuptools wheel
  pip_in_env tts-crisperwhisper install -U faster-whisper crisperwhisper
  if [[ "$RUN_IMPORT_CHECKS" == "1" ]]; then
    python_in_env tts-crisperwhisper - <<'PY'
import faster_whisper
import crisperwhisper
print("crisperwhisper import ok")
PY
  fi
}

install_video_downloader() {
  [[ "$INSTALL_VIDEO_DL" == "1" ]] || { log "Skipping video downloader"; return 0; }
  log "Installing/checking HandAI Video Downloader"
  mkdir -p "$(dirname "$VIDEO_DL_DIR")"
  if [[ -d "${VIDEO_DL_DIR}/.git" ]]; then
    git -C "$VIDEO_DL_DIR" pull --ff-only || warn "video-dl git pull failed; continuing with existing checkout."
  elif [[ -d "$VIDEO_DL_DIR" && -n "$(find "$VIDEO_DL_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -1)" ]]; then
    warn "${VIDEO_DL_DIR} exists but is not a git checkout. Leaving it untouched."
  else
    rm -rf "$VIDEO_DL_DIR"
    git clone "$VIDEO_DL_REPO" "$VIDEO_DL_DIR"
  fi

  if [[ -x "${VIDEO_DL_DIR}/install.sh" ]]; then
    (cd "$VIDEO_DL_DIR" && ./install.sh)
  else
    warn "video downloader install.sh not executable or missing: ${VIDEO_DL_DIR}/install.sh"
  fi

  if [[ -x "${VIDEO_DL_DIR}/video-dl" ]]; then
    "${VIDEO_DL_DIR}/video-dl" --help >/dev/null || warn "video-dl exists but --help returned a warning/error."
    echo "video-dl launcher OK: ${VIDEO_DL_DIR}/video-dl"
  else
    warn "video-dl root launcher missing or not executable: ${VIDEO_DL_DIR}/video-dl"
  fi
}

ensure_huggingface_token() {
  local token_file="${TTS_CONFIG_DIR}/huggingface_token"
  if [[ -s "$token_file" ]]; then
    echo "Hugging Face token already stored: ${token_file}"
    return 0
  fi
  if [[ -n "${HF_TOKEN:-}" ]]; then
    echo "Using HF_TOKEN from environment."
    printf '%s\n' "$HF_TOKEN" > "$token_file"
    chmod 600 "$token_file"
    return 0
  fi
  if [[ "$ASSUME_YES" == "1" ]]; then
    warn "No Hugging Face token provided. Some model downloads may fail. Set HF_TOKEN or run login-hf-token.sh later."
    return 0
  fi
  echo
  echo "Some models require a Hugging Face token. Leave blank to skip (you can add one later via login-hf-token.sh)."
  read -r -p "Paste Hugging Face token: " token
  if [[ -n "$token" ]]; then
    printf '%s\n' "$token" > "$token_file"
    chmod 600 "$token_file"
    echo "Token saved to ${token_file}"
  fi
}

write_env_example() {
  log "Writing environment example"
  cat > "${TTS_LAB}/stack-env.example" <<EOF
# Optional overrides for TTS Lab / Web UI integration
export TTS_LAB="${TTS_LAB}"
export TTS_APP_DIR="${TTS_APP_DIR}"
export TTS_DATA_DIR="${TTS_DATA_DIR}"
export TTS_MODEL_DIR="${TTS_MODEL_DIR}"
export TTS_OUT="${TTS_OUT}"
export TTS_REF="${TTS_REF}"
export TTS_JOB_DIR="${TTS_JOB_DIR}"
export TTS_TAGGED_WORKSPACE_DIR="${TTS_TAGGED_WORKSPACE_DIR}"
export TTS_CONFIG_DIR="${TTS_CONFIG_DIR}"
export CONDA_ROOT="${CONDA_ROOT}"
export VIDEO_DL_DIR="${VIDEO_DL_DIR}"
export TTS_VIDEO_DL_CMD='${VIDEO_DL_DIR}/video-dl {url} {out}'
# export TTS_AUDACITY_CMD='audacity'
EOF
}

generate_bridge_token() {
  local token_file="${TTS_CONFIG_DIR}/ai_studio_bridge_token"
  if [[ -s "$token_file" ]]; then
    echo "AI Studio bridge token already exists: ${token_file}"
    return 0
  fi
  log "Generating AI Studio bridge token"
  local token
  token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  printf '%s\n' "$token" > "$token_file"
  chmod 600 "$token_file"
  echo "Bridge token saved to ${token_file}"
}

run_smoke_tests() {
  [[ "$RUN_SMOKE_TESTS" == "1" ]] || { log "Skipping smoke tests. Use --run-smoke-tests to render test WAVs."; return 0; }
  log "Running smoke tests"

  local ref_wav="${TTS_REF}/voice_ref.wav"
  if [[ ! -f "$ref_wav" ]]; then
    log "Generating synthetic reference WAV for smoke tests"
    python_in_env tts-whisper - <<'PY'
import numpy as np, wave, os, pathlib
ref = pathlib.Path(os.environ["TTS_REF"]) / "voice_ref.wav"
ref.parent.mkdir(parents=True, exist_ok=True)
sr = 16000
duration = 5
freq = 440
samples = (np.sin(2 * np.pi * freq * np.arange(sr * duration) / sr) * 0.5 * 32767).astype(np.int16)
with wave.open(str(ref), "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sr)
    wf.writeframes(samples.tobytes())
print(f"wrote {ref}")
PY
  fi

  if [[ "$INSTALL_CHATTERBOX" == "1" ]]; then
    log "Smoke test: Chatterbox synthesis"
    "${TTS_LAB}/tts-lab.sh" synth chatterbox --text "Hello from HandAI TTS Lab." --out "${TTS_OUT}/smoke_chatterbox.wav"
  fi

  if [[ "$INSTALL_QWEN3" == "1" ]]; then
    log "Smoke test: Qwen3 synthesis"
    "${TTS_LAB}/tts-lab.sh" synth qwen3 --text "Status update." --x-vector-only --out "${TTS_OUT}/smoke_qwen3.wav"
  fi

  if [[ "$INSTALL_WHISPER" == "1" ]]; then
    log "Smoke test: Faster-Whisper transcription"
    python_in_env tts-whisper - <<'PY'
from faster_whisper import WhisperModel
import os
ref = os.path.join(os.environ["TTS_REF"], "voice_ref.wav")
out = os.path.join(os.environ["TTS_OUT"], "smoke_whisper.txt")
model = WhisperModel("base", device="cuda", compute_type="float16")
segs, info = model.transcribe(ref)
with open(out, "w") as f:
    for seg in segs:
        f.write(f"[{seg.start:.2f} -> {seg.end:.2f}] {seg.text}\n")
print(f"wrote {out}")
PY
  fi

  echo "Smoke test outputs in ${TTS_OUT}/smoke_*.wav and ${TTS_OUT}/smoke_whisper.txt"
}

summary() {
  log "Install summary"
  echo "TTS Lab: ${TTS_LAB}"
  echo "App code: ${TTS_APP_DIR}"
  echo "Data: ${TTS_DATA_DIR}"
  echo "Models: ${TTS_MODEL_DIR}"
  echo "Launcher: ${TTS_LAB}/tts-lab.sh"
  echo "Logs: ${LOG_FILE}"
  [[ -x "${VIDEO_DL_DIR}/video-dl" ]] && echo "Video downloader: ${VIDEO_DL_DIR}/video-dl" || echo "Video downloader: missing/not executable"
  echo
  "${TTS_LAB}/tts-lab.sh" status || true
  echo
  echo "Next useful commands:"
  echo "  ${TTS_LAB}/tts-lab.sh status"
  echo "  ${TTS_LAB}/start-tts-webui.sh"
  echo "  ${TTS_LAB}/tts-lab.sh synth chatterbox --text 'Hello from the local TTS lab.'"
}

main() {
  preflight
  if [[ "$INSTALL_ENGINES" == "1" ]]; then
    plan_engines
  else
    log "Skipping engine planning because engine installation is disabled"
  fi
  install_system_deps
  if [[ "$INSTALL_ENGINES" == "1" || "$RUN_SMOKE_TESTS" == "1" ]]; then
    install_conda
  else
    log "Skipping Conda check/install because engine installation is disabled"
  fi
  create_lab_folders
  write_launcher_scripts
  install_video_downloader
  ensure_huggingface_token
  install_chatterbox
  download_chatterbox_model
  install_whisper
  download_whisper_model
  install_qwen3
  install_cosyvoice
  install_f5_experimental
  install_resemble_enhance
  install_whisperx
  install_crisperwhisper
  generate_bridge_token
  write_env_example
  run_smoke_tests
  summary
}

main "$@"
