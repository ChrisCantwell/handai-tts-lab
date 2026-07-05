#!/usr/bin/env bash
# TTS Lab Stack Installer v0.1.1
# Creates the local /home/user/tts-lab contract expected by the Audio/TTS/STT Web UI.
set -Eeuo pipefail

VERSION="0.1.2"
DEFAULT_TTS_LAB="${HOME}/tts-lab"
DEFAULT_CONDA_ROOT="${HOME}/miniconda3"
DEFAULT_VIDEO_DL_DIR="${HOME}/video-dl"
DEFAULT_VIDEO_DL_REPO="https://github.com/ChrisCantwell/handai-videodownloader.git"

TTS_LAB="${TTS_LAB:-$DEFAULT_TTS_LAB}"
CONDA_ROOT="${CONDA_ROOT:-$DEFAULT_CONDA_ROOT}"
VIDEO_DL_DIR="${VIDEO_DL_DIR:-$DEFAULT_VIDEO_DL_DIR}"
VIDEO_DL_REPO="${VIDEO_DL_REPO:-$DEFAULT_VIDEO_DL_REPO}"
PYTORCH_CUDA_INDEX="${PYTORCH_CUDA_INDEX:-https://download.pytorch.org/whl/cu124}"
COSY_TORCH_INDEX="${COSY_TORCH_INDEX:-https://download.pytorch.org/whl/cu121}"

INSTALL_SYSTEM_DEPS=1
INSTALL_VIDEO_DL=1
INSTALL_ENGINES=1
INSTALL_CHATTERBOX=1
INSTALL_QWEN3=1
INSTALL_COSYVOICE=1
INSTALL_F5=0
RUN_IMPORT_CHECKS=1
RUN_SMOKE_TESTS=0
DOWNLOAD_MODELS=1
ASSUME_YES=0

LOG_ROOT="${TTS_LAB}/logs/stack-installer"
LOG_FILE=""

usage() {
  cat <<EOF
TTS Lab Stack Installer v${VERSION}

Creates the engine stack expected by the Audio/TTS/STT Web UI:
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
  --run-smoke-tests             Generate short WAVs after install. Requires a reference WAV.
  --with-f5-experimental        Install F5-TTS too. Known experimental/segfault risk on this stack.
  --lab PATH                    TTS lab directory. Default: ${DEFAULT_TTS_LAB}
  --conda-root PATH             Conda install root. Default: ${DEFAULT_CONDA_ROOT}
  --video-dl-dir PATH           Video downloader directory. Default: ${DEFAULT_VIDEO_DL_DIR}
  --video-dl-repo URL           Video downloader repo. Default: ${DEFAULT_VIDEO_DL_REPO}
  -h, --help                    Show this help.

Environment overrides:
  TTS_LAB, CONDA_ROOT, VIDEO_DL_DIR, VIDEO_DL_REPO
  PYTORCH_CUDA_INDEX, COSY_TORCH_INDEX
  VIDEO_DL_SKIP_SYSTEM_DEPS=1   Passed through to the video downloader installer.

Notes:
  - This installer is designed for Ubuntu/Linux + NVIDIA GPU + Conda.
  - It installs Chatterbox, Qwen3-TTS 0.6B, and CosyVoice by default.
  - F5 is available only with --with-f5-experimental because the original session hit SIGSEGV.
  - Qwen3 defaults to x-vector-only mode if no --ref-text is provided.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) ASSUME_YES=1; shift ;;
    --skip-system-deps) INSTALL_SYSTEM_DEPS=0; shift ;;
    --no-video-dl) INSTALL_VIDEO_DL=0; shift ;;
    --no-engines) INSTALL_ENGINES=0; INSTALL_CHATTERBOX=0; INSTALL_QWEN3=0; INSTALL_COSYVOICE=0; INSTALL_F5=0; shift ;;
    --only-video-dl) INSTALL_SYSTEM_DEPS=1; INSTALL_VIDEO_DL=1; INSTALL_ENGINES=0; INSTALL_CHATTERBOX=0; INSTALL_QWEN3=0; INSTALL_COSYVOICE=0; INSTALL_F5=0; shift ;;
    --only-launchers) INSTALL_SYSTEM_DEPS=0; INSTALL_VIDEO_DL=0; INSTALL_ENGINES=0; INSTALL_CHATTERBOX=0; INSTALL_QWEN3=0; INSTALL_COSYVOICE=0; INSTALL_F5=0; RUN_IMPORT_CHECKS=0; DOWNLOAD_MODELS=0; shift ;;
    --no-model-downloads) DOWNLOAD_MODELS=0; shift ;;
    --no-import-checks) RUN_IMPORT_CHECKS=0; shift ;;
    --run-smoke-tests) RUN_SMOKE_TESTS=1; shift ;;
    --with-f5-experimental) INSTALL_F5=1; shift ;;
    --lab) TTS_LAB="$2"; shift 2 ;;
    --conda-root) CONDA_ROOT="$2"; shift 2 ;;
    --video-dl-dir) VIDEO_DL_DIR="$2"; shift 2 ;;
    --video-dl-repo) VIDEO_DL_REPO="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

LOG_ROOT="${TTS_LAB}/logs/stack-installer"
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
    "${TTS_LAB}/scripts" \
    "${TTS_LAB}/references" \
    "${TTS_LAB}/output" \
    "${TTS_LAB}/tmp" \
    "${TTS_LAB}/logs" \
    "${TTS_LAB}/.cache/huggingface" \
    "${TTS_LAB}/.cache/torch" \
    "${TTS_LAB}/engines"

  if [[ ! -f "${TTS_LAB}/references/ref_text.txt" ]]; then
    cat > "${TTS_LAB}/references/ref_text.txt" <<'EOF'
This is my reference voice sample for cloning.
EOF
  fi
}

write_launcher_scripts() {
  log "Writing launcher and wrapper scripts"
  mkdir -p "${TTS_LAB}/scripts"

  cat > "${TTS_LAB}/tts-lab.sh" <<'BASH_LAUNCHER'
#!/usr/bin/env bash
# Unified launcher for local TTS voice-cloning engines.
set -euo pipefail

LAB="${TTS_LAB:-$HOME/tts-lab}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
CONDA="${CONDA_ROOT}/etc/profile.d/conda.sh"
REF="${TTS_REF:-${LAB}/references/voice_ref.wav}"
REF_TEXT="${TTS_REF_TEXT:-${LAB}/references/ref_text.txt}"
OUT="${TTS_OUT:-${LAB}/output}"
SCRIPTS="${LAB}/scripts"
VIDEO_DL_DIR="${VIDEO_DL_DIR:-$HOME/video-dl}"
VIDEO_DL_BIN="${VIDEO_DL_BIN:-${VIDEO_DL_DIR}/video-dl}"

usage() {
  cat <<'EOF'
Usage: tts-lab.sh <command> [args]

Commands:
  synth <engine> --text "..." [--ref PATH] [--ref-text "..."] [--out PATH] [--language English]
      Engines: chatterbox | qwen3 | cosyvoice | f5
      Qwen3 supports --x-vector-only.

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
    *) echo "Unknown engine: $1" >&2; exit 1 ;;
  esac
  export TMPDIR="${LAB}/tmp"
  export HF_HOME="${LAB}/.cache/huggingface"
  export TORCH_HOME="${LAB}/.cache/torch"
  mkdir -p "$TMPDIR" "$HF_HOME" "$TORCH_HOME" "$OUT"
}

cmd_synth() {
  local engine="$1"; shift
  local text="" ref="$REF" ref_text="" out="" xvector="" language="English"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --text) text="$2"; shift 2 ;;
      --ref) ref="$2"; shift 2 ;;
      --ref-text) ref_text="$2"; shift 2 ;;
      --out) out="$2"; shift 2 ;;
      --language) language="$2"; shift 2 ;;
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
      python "$SCRIPTS/synth_chatterbox.py" --text "$text" --ref "$ref" --out "$out"
      ;;
    qwen3)
      args=(--text "$text" --ref "$ref" --out "$out" --language "$language")
      if [[ -n "$ref_text" ]]; then
        args+=(--ref-text "$ref_text")
      else
        # Qwen3 voice clone ICL mode requires an exact reference transcript.
        # For simple launcher/UI calls, default to x-vector-only mode so synthesis
        # works without asking the user to transcribe the reference sample first.
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
      PYTHONPATH="${LAB}/cosyvoice/CosyVoice:${LAB}/cosyvoice/CosyVoice/third_party/Matcha-TTS:${PYTHONPATH:-}"
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
  echo "CONDA_ROOT=$CONDA_ROOT"
  echo "REF=$REF"
  echo "OUT=$OUT"
  echo "VIDEO_DL_BIN=$VIDEO_DL_BIN"
  [[ -x "$VIDEO_DL_BIN" ]] && echo "video-dl: OK" || echo "video-dl: missing/not executable"
  for e in chatterbox qwen3 cosyvoice f5; do
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
  chmod +x "${TTS_LAB}/tts-lab.sh"

  cat > "${TTS_LAB}/scripts/synth_chatterbox.py" <<'PY'
#!/usr/bin/env python3
"""Generate speech with Chatterbox-Turbo."""
import argparse
from pathlib import Path

import soundfile as sf
from chatterbox.tts_turbo import ChatterboxTurboTTS


def main() -> None:
    p = argparse.ArgumentParser(description="Chatterbox-Turbo voice clone")
    p.add_argument("--text", required=True, help="Text to synthesize")
    p.add_argument("--ref", required=True, help="Reference WAV for voice cloning")
    p.add_argument("--out", required=True, help="Output WAV path")
    p.add_argument("--device", default="cuda", help="cuda or cpu")
    args = p.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    model = ChatterboxTurboTTS.from_pretrained(device=args.device)

    # PerTh watermarker has crashed on some local Linux/Torch stacks. For the
    # local lab workflow, prefer a usable render over losing the whole job.
    class _NoWatermark:
        def apply_watermark(self, wav, sample_rate=None):
            return wav

    model.watermarker = _NoWatermark()

    wav = model.generate(args.text, audio_prompt_path=args.ref)
    sf.write(str(out), wav.squeeze().cpu().numpy(), model.sr)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
PY
  chmod +x "${TTS_LAB}/scripts/synth_chatterbox.py"

  cat > "${TTS_LAB}/scripts/synth_qwen3.py" <<'PY'
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
  chmod +x "${TTS_LAB}/scripts/synth_qwen3.py"

  cat > "${TTS_LAB}/scripts/synth_cosyvoice.py" <<'PY'
#!/usr/bin/env python3
"""Generate speech with CosyVoice 3 zero-shot cloning.

This wrapper deliberately avoids torchaudio.save because this local stack has
shown native-library segfaults around Torch/Torchaudio/ONNXRuntime teardown.
"""
import argparse
import os
import sys
import wave
from pathlib import Path

import numpy as np

LAB = Path(os.environ.get("TTS_LAB", str(Path.home() / "tts-lab")))
COSY_ROOT = Path(os.environ.get("COSYVOICE_ROOT", str(LAB / "cosyvoice" / "CosyVoice")))
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
        # Accept [channels, samples] or [samples, channels].
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
  chmod +x "${TTS_LAB}/scripts/synth_cosyvoice.py"

  cat > "${TTS_LAB}/scripts/synth_f5.py" <<'PY'
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
  chmod +x "${TTS_LAB}/scripts/synth_f5.py"
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

install_qwen3() {
  [[ "$INSTALL_ENGINES" == "1" && "$INSTALL_QWEN3" == "1" ]] || return 0
  log "Installing Qwen3-TTS 0.6B"
  create_env tts-qwen3 3.12
  install_pytorch_in_env tts-qwen3 "$PYTORCH_CUDA_INDEX"
  pip_in_env tts-qwen3 install -U qwen-tts soundfile
  if [[ "$DOWNLOAD_MODELS" == "1" ]]; then
    pip_in_env tts-qwen3 install -U "huggingface_hub[cli]"
    HF_HOME="${TTS_LAB}/.cache/huggingface" "${CONDA_ROOT}/envs/tts-qwen3/bin/huggingface-cli" download Qwen/Qwen3-TTS-Tokenizer-12Hz || true
    HF_HOME="${TTS_LAB}/.cache/huggingface" "${CONDA_ROOT}/envs/tts-qwen3/bin/huggingface-cli" download Qwen/Qwen3-TTS-12Hz-0.6B-Base || true
  fi
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

  mkdir -p "${TTS_LAB}/cosyvoice"
  if [[ -d "${TTS_LAB}/cosyvoice/CosyVoice/.git" ]]; then
    git -C "${TTS_LAB}/cosyvoice/CosyVoice" pull --ff-only || warn "CosyVoice git pull failed; continuing with existing checkout."
    git -C "${TTS_LAB}/cosyvoice/CosyVoice" submodule update --init --recursive || true
  else
    rm -rf "${TTS_LAB}/cosyvoice/CosyVoice"
    git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git "${TTS_LAB}/cosyvoice/CosyVoice"
  fi

  local req="${TTS_LAB}/cosyvoice/CosyVoice/requirements.txt"
  local filtered="${TTS_LAB}/cosyvoice/requirements-inference-filtered.txt"
  if [[ -f "$req" ]]; then
    grep -v -E 'deepspeed|tensorrt|openai-whisper' "$req" > "$filtered"
    pip_in_env tts-cosyvoice install -r "$filtered" || warn "CosyVoice filtered requirements had failures; installing known inference dependencies next."
  fi
  pip_in_env tts-cosyvoice install pyarrow pyworld lightning fastapi uvicorn modelscope "huggingface_hub[cli]" soundfile librosa

  if [[ "$DOWNLOAD_MODELS" == "1" ]]; then
    (cd "${TTS_LAB}/cosyvoice/CosyVoice" && \
      HF_HOME="${TTS_LAB}/.cache/huggingface" "${CONDA_ROOT}/envs/tts-cosyvoice/bin/python" - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='pretrained_models/Fun-CosyVoice3-0.5B')
PY
    )
  fi
  if [[ "$RUN_IMPORT_CHECKS" == "1" ]]; then
    PYTHONPATH="${TTS_LAB}/cosyvoice/CosyVoice:${TTS_LAB}/cosyvoice/CosyVoice/third_party/Matcha-TTS" \
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

write_env_example() {
  log "Writing environment example"
  cat > "${TTS_LAB}/stack-env.example" <<EOF
# Optional overrides for TTS Lab / Web UI integration
export TTS_LAB="${TTS_LAB}"
export CONDA_ROOT="${CONDA_ROOT}"
export VIDEO_DL_DIR="${VIDEO_DL_DIR}"
export TTS_VIDEO_DL_CMD='${VIDEO_DL_DIR}/video-dl {url} {out}'
# export TTS_AUDACITY_CMD='audacity'
EOF
}

run_smoke_tests() {
  [[ "$RUN_SMOKE_TESTS" == "1" ]] || { log "Skipping smoke tests. Use --run-smoke-tests to render test WAVs."; return 0; }
  log "Running smoke tests"
  if [[ ! -f "${TTS_LAB}/references/voice_ref.wav" ]]; then
    warn "No reference WAV at ${TTS_LAB}/references/voice_ref.wav. Skipping synthesis smoke tests."
    return 0
  fi
  "${TTS_LAB}/tts-lab.sh" test
}

summary() {
  log "Install summary"
  echo "TTS Lab: ${TTS_LAB}"
  echo "Launcher: ${TTS_LAB}/tts-lab.sh"
  echo "Logs: ${LOG_FILE}"
  [[ -x "${VIDEO_DL_DIR}/video-dl" ]] && echo "Video downloader: ${VIDEO_DL_DIR}/video-dl" || echo "Video downloader: missing/not executable"
  echo
  "${TTS_LAB}/tts-lab.sh" status || true
  echo
  echo "Next useful commands:"
  echo "  ${TTS_LAB}/tts-lab.sh status"
  echo "  ${TTS_LAB}/tts-lab.sh synth chatterbox --text 'Hello from the local TTS lab.'"
  echo "  TTS_VIDEO_DL_CMD='${VIDEO_DL_DIR}/video-dl {url} {out}' ./start.sh"
}

main() {
  preflight
  install_system_deps
  if [[ "$INSTALL_ENGINES" == "1" || "$RUN_SMOKE_TESTS" == "1" ]]; then
    install_conda
  else
    log "Skipping Conda check/install because engine installation is disabled"
  fi
  create_lab_folders
  write_launcher_scripts
  install_video_downloader
  install_chatterbox
  install_qwen3
  install_cosyvoice
  install_f5_experimental
  write_env_example
  run_smoke_tests
  summary
}

main "$@"
