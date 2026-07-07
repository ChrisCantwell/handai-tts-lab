#!/usr/bin/env bash
set -euo pipefail

LAB="${TTS_LAB:-/home/user/tts-lab}"
WEBUI="$LAB/webui"
LAUNCHER="$LAB/tts-lab.sh"
APP_VERSION="$(awk -F'\"' '/^VERSION =/ {print $2; exit}' tts_webui.py 2>/dev/null || true)"
if [[ -z "$APP_VERSION" ]]; then
  APP_VERSION="unknown"
fi
echo "Installing TTS Lab Unified Web UI v${APP_VERSION}"

if [[ ! -f "$LAUNCHER" ]]; then
  echo "ERROR: expected launcher not found: $LAUNCHER" >&2
  echo "Run this on the machine where Grok created /home/user/tts-lab." >&2
  exit 1
fi

mkdir -p "$WEBUI" "$LAB/output" "$LAB/output/job_history" "$LAB/output/audio_lab" "$LAB/output/video_intake/source_media/uploads" "$LAB/output/video_intake/source_media/url_imports" "$LAB/output/video_intake/extracted_audio" "$LAB/output/resemble_enhance" "$LAB/resemble_uploads" "$LAB/engines/resemble-enhance" "$LAB/references" "$LAB/references/profiles" "$LAB/stt_uploads" "$LAB/config"
cp tts_webui.py "$WEBUI/tts_webui.py"
cp stt_faster_whisper.py "$WEBUI/stt_faster_whisper.py"
if [[ -f tts_ai_studio_bridge.py ]]; then
  cp tts_ai_studio_bridge.py "$WEBUI/tts_ai_studio_bridge.py"
fi
if [[ -f run-ai-studio-bridge.sh ]]; then
  cp run-ai-studio-bridge.sh "$WEBUI/run-ai-studio-bridge.sh"
fi
if [[ -f .env.ai-studio-bridge.example ]]; then
  cp .env.ai-studio-bridge.example "$WEBUI/.env.ai-studio-bridge.example"
fi
chmod +x "$WEBUI/tts_webui.py" "$WEBUI/stt_faster_whisper.py"
if [[ -f "$WEBUI/tts_ai_studio_bridge.py" ]]; then chmod +x "$WEBUI/tts_ai_studio_bridge.py"; fi
if [[ -f "$WEBUI/run-ai-studio-bridge.sh" ]]; then chmod +x "$WEBUI/run-ai-studio-bridge.sh"; fi

cat > "$LAB/start-tts-webui.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export TTS_LAB="${LAB}"
export TTS_WEBUI_HOST="\${TTS_WEBUI_HOST:-127.0.0.1}"
export TTS_WEBUI_PORT="\${TTS_WEBUI_PORT:-7870}"
# If optional CUDA runtime wheels were installed into tts-whisper, expose their lib dirs.
WHISPER_SITE="\$HOME/miniconda3/envs/tts-whisper/lib/python3.11/site-packages"
if [[ -d "\$WHISPER_SITE/nvidia" ]]; then
  CUDA_LIBS="\$(find "\$WHISPER_SITE/nvidia" -type d -name lib 2>/dev/null | paste -sd: -)"
  if [[ -n "\$CUDA_LIBS" ]]; then
    export LD_LIBRARY_PATH="\$CUDA_LIBS:\${LD_LIBRARY_PATH:-}"
  fi
fi
exec /usr/bin/env python3 "${WEBUI}/tts_webui.py"
EOF
chmod +x "$LAB/start-tts-webui.sh"

cat > "$LAB/start-ai-studio-bridge.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export TTS_LAB="${LAB}"
export TTS_WEBUI_BASE="\${TTS_WEBUI_BASE:-http://127.0.0.1:7870}"
export TTS_AI_STUDIO_BRIDGE_HOST="\${TTS_AI_STUDIO_BRIDGE_HOST:-127.0.0.1}"
export TTS_AI_STUDIO_BRIDGE_PORT="\${TTS_AI_STUDIO_BRIDGE_PORT:-7871}"
export TTS_AI_STUDIO_BRIDGE_ALLOWED_ORIGINS="\${TTS_AI_STUDIO_BRIDGE_ALLOWED_ORIGINS:-*}"
export TTS_AI_STUDIO_BRIDGE_ALLOWED_ENGINES="\${TTS_AI_STUDIO_BRIDGE_ALLOWED_ENGINES:-chatterbox,qwen3,cosyvoice}"
: "\${TTS_AI_STUDIO_BRIDGE_TOKEN:?Set TTS_AI_STUDIO_BRIDGE_TOKEN before starting the bridge}"
exec /usr/bin/env python3 "${WEBUI}/tts_ai_studio_bridge.py"
EOF
chmod +x "$LAB/start-ai-studio-bridge.sh"


cat > "$WEBUI/README_INSTALLED.txt" <<EOF
TTS Lab Unified Web UI v${APP_VERSION} installed.

Start it with:
  $LAB/start-tts-webui.sh

Open:
  http://127.0.0.1:7870

Override host/port if needed:
  TTS_WEBUI_HOST=0.0.0.0 TTS_WEBUI_PORT=7870 $LAB/start-tts-webui.sh

Profile library:
  $LAB/references/profiles

Optional AI Studio bridge sidecar:
  export TTS_AI_STUDIO_BRIDGE_TOKEN=your-long-random-token
  $LAB/start-ai-studio-bridge.sh
  http://127.0.0.1:7871

Tunnel only the bridge port if using Cloudflare quick tunnels; do not tunnel the full Web UI.
EOF

cat > "$LAB/install-whisper.sh" <<'WHISPERINSTALL'
#!/usr/bin/env bash
set -euo pipefail
LAB="${TTS_LAB:-/home/user/tts-lab}"
CONDA="${CONDA_EXE:-/home/user/miniconda3/bin/conda}"
if [[ ! -x "$CONDA" ]]; then
  echo "ERROR: conda not found at $CONDA" >&2
  echo "Install Miniconda first or set CONDA_EXE=/path/to/conda" >&2
  exit 1
fi
source "$(dirname "$CONDA")/../etc/profile.d/conda.sh"
if ! conda env list | awk '{print $1}' | grep -qx 'tts-whisper'; then
  conda create -n tts-whisper python=3.11 -y
fi
conda activate tts-whisper
python -m pip install --upgrade pip
python -m pip install -U faster-whisper "huggingface_hub[cli]"
python - <<'PYREADY'
import faster_whisper
print('faster-whisper ready:', faster_whisper.__version__)
PYREADY
echo "Whisper STT env ready. Restart the web UI if it is already running."
WHISPERINSTALL
chmod +x "$LAB/install-whisper.sh"

cat > "$LAB/login-hf-token.sh" <<'HFLOGIN'
#!/usr/bin/env bash
set -euo pipefail
CONDA="${CONDA_EXE:-/home/user/miniconda3/bin/conda}"
if [[ ! -x "$CONDA" ]]; then
  echo "ERROR: conda not found at $CONDA" >&2
  exit 1
fi
source "$(dirname "$CONDA")/../etc/profile.d/conda.sh"
conda activate tts-whisper
if command -v hf >/dev/null 2>&1; then
  echo "Paste a READ-ONLY Hugging Face token. Do not paste tokens into chat or public logs."
  hf auth login
else
  echo "Paste a READ-ONLY Hugging Face token. Do not paste tokens into chat or public logs."
  huggingface-cli login
fi
HFLOGIN
chmod +x "$LAB/login-hf-token.sh"

cat > "$LAB/install-whisper-cuda-libs.sh" <<'CUDALIBS'
#!/usr/bin/env bash
set -euo pipefail
CONDA="${CONDA_EXE:-/home/user/miniconda3/bin/conda}"
if [[ ! -x "$CONDA" ]]; then
  echo "ERROR: conda not found at $CONDA" >&2
  exit 1
fi
source "$(dirname "$CONDA")/../etc/profile.d/conda.sh"
conda activate tts-whisper
python -m pip install -U nvidia-cublas-cu12 nvidia-cudnn-cu12
python - <<'PYCUDA'
import glob, os, site
roots = []
for base in site.getsitepackages():
    roots.extend(glob.glob(os.path.join(base, 'nvidia', '*', 'lib')))
print('Installed NVIDIA library dirs:')
for r in roots:
    print(' ', r)
print('Restart the web UI after this. start-tts-webui.sh will add these dirs to LD_LIBRARY_PATH.')
PYCUDA
CUDALIBS
chmod +x "$LAB/install-whisper-cuda-libs.sh"

cat > "$LAB/install-resemble-enhance.sh" <<'RESEMBLEINSTALL'
#!/usr/bin/env bash
set -euo pipefail

LAB="${TTS_LAB:-/home/user/tts-lab}"
ROOT="${TTS_RESEMBLE_ROOT:-$LAB/engines/resemble-enhance}"
OUT="${TTS_RESEMBLE_OUTPUT_DIR:-$LAB/output/resemble_enhance}"
MODE="${TTS_RESEMBLE_INSTALL_MODE:-auto}"
ENV_NAME="${TTS_RESEMBLE_CONDA_ENV:-tts-resemble-enhance}"
PY_VERSION="${TTS_RESEMBLE_PYTHON_VERSION:-3.10}"
PRE_FLAG="${TTS_RESEMBLE_PRE:-0}"

mkdir -p "$ROOT" "$OUT" "$LAB/config"

echo "Resemble Enhance isolated installer"
echo "LAB: $LAB"
echo "ROOT: $ROOT"
echo "OUTPUT: $OUT"
echo "Requested mode: $MODE"
echo "Conda env name: $ENV_NAME"
echo "Python version preference: $PY_VERSION"
echo

find_conda() {
  if [[ -n "${CONDA_EXE:-}" && -x "${CONDA_EXE:-}" ]]; then
    printf '%s\n' "$CONDA_EXE"
    return 0
  fi
  if [[ -x "$HOME/miniconda3/bin/conda" ]]; then
    printf '%s\n' "$HOME/miniconda3/bin/conda"
    return 0
  fi
  if [[ -x "$HOME/anaconda3/bin/conda" ]]; then
    printf '%s\n' "$HOME/anaconda3/bin/conda"
    return 0
  fi
  command -v conda 2>/dev/null || true
}

CONDA="$(find_conda)"
if [[ "$MODE" == "auto" ]]; then
  if [[ -n "$CONDA" ]]; then
    MODE="conda"
  else
    MODE="venv"
  fi
fi

echo "Resolved install mode: $MODE"
if [[ -n "$CONDA" ]]; then
  echo "Conda detected: $CONDA"
else
  echo "Conda not detected. Venv mode remains available."
fi
echo

PIP_ARGS=(install --upgrade resemble-enhance)
if [[ "$PRE_FLAG" == "1" || "$PRE_FLAG" == "true" ]]; then
  PIP_ARGS+=(--pre)
fi

if [[ "$MODE" == "conda" ]]; then
  if [[ -z "$CONDA" || ! -x "$CONDA" ]]; then
    echo "ERROR: conda mode requested but conda was not found." >&2
    echo "Set CONDA_EXE=/path/to/conda or use install mode 'venv'." >&2
    exit 1
  fi
  # shellcheck source=/dev/null
  source "$(dirname "$CONDA")/../etc/profile.d/conda.sh"
  if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    echo "Creating conda environment $ENV_NAME with python=$PY_VERSION"
    conda create -n "$ENV_NAME" "python=$PY_VERSION" -y
  else
    echo "Conda environment $ENV_NAME already exists; reusing it."
  fi
  conda activate "$ENV_NAME"
  echo "Python: $(python --version)"
  python -m pip install --upgrade pip setuptools wheel
  python -m pip "${PIP_ARGS[@]}"
  echo
  echo "Installing Git LFS into the isolated Resemble conda environment for model downloads."
  conda install -n "$ENV_NAME" -c conda-forge git-lfs -y || echo "WARNING: conda git-lfs install failed; you can repair it later from Maintenance."
  git lfs install --skip-repo || true
  git lfs version || true
  echo
  echo "Installed command: $(command -v resemble-enhance || true)"
  resemble-enhance --help | head -80 || true
  echo
  echo "Resemble Enhance conda environment is ready: $ENV_NAME"
  exit 0
fi

if [[ "$MODE" == "venv" ]]; then
  PYTHON_BIN="${TTS_RESEMBLE_PYTHON_BIN:-python3}"
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "ERROR: python3 was not found for venv mode." >&2
    echo "Install Python venv support or use conda mode." >&2
    exit 1
  fi
  ENV_DIR="$ROOT/.venv"
  if [[ ! -d "$ENV_DIR" ]]; then
    echo "Creating Python venv: $ENV_DIR"
    "$PYTHON_BIN" -m venv "$ENV_DIR"
  else
    echo "Python venv already exists; reusing it: $ENV_DIR"
  fi
  # shellcheck source=/dev/null
  source "$ENV_DIR/bin/activate"
  echo "Python: $(python --version)"
  python -m pip install --upgrade pip setuptools wheel
  python -m pip "${PIP_ARGS[@]}"
  echo
  if git lfs version >/dev/null 2>&1; then
    echo "Git LFS detected for model downloads: $(git lfs version)"
  else
    echo "WARNING: git-lfs was not found. Resemble may fail while downloading model files. Use conda mode or Maintenance -> Resemble Enhance -> Install/repair Git LFS if conda is available."
  fi
  echo
  echo "Installed command: $(command -v resemble-enhance || true)"
  resemble-enhance --help | head -80 || true
  echo
  echo "Resemble Enhance venv is ready: $ENV_DIR"
  exit 0
fi

echo "ERROR: unknown install mode: $MODE" >&2
echo "Use auto, conda, or venv." >&2
exit 1
RESEMBLEINSTALL
chmod +x "$LAB/install-resemble-enhance.sh"


cat > "$LAB/engines/resemble-enhance/resemble_enhance_webui_wrapper.py" <<'RESEMBLEWRAPPER'
#!/usr/bin/env python3
"""Direct Resemble Enhance runner for TTS Lab Web UI.

This keeps the installed package unmodified while avoiding fragile behavior in
some packaged CLI builds. It processes .wav files from an input directory,
coerces pathlib paths to strings for torchaudio, prints step-by-step diagnostics,
and exits non-zero if no output file is written.
"""
from __future__ import annotations

import argparse
import random
import sys
import time
import traceback
from pathlib import Path


def _log(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("in_dir", type=Path, help="Path to input audio folder")
    parser.add_argument("out_dir", type=Path, help="Output folder")
    parser.add_argument("--run_dir", type=Path, default=None, help="Path to the enhancer run folder, if None, use the default model")
    parser.add_argument("--suffix", type=str, default=".wav", help="Audio file suffix")
    parser.add_argument("--device", type=str, default="cuda", help="Device to use: cuda, cpu, or auto")
    parser.add_argument("--denoise_only", action="store_true", help="Only apply denoising without enhancement")
    parser.add_argument("--lambd", type=float, default=1.0, help="Denoise strength for enhancement (0.0 to 1.0)")
    parser.add_argument("--tau", type=float, default=0.5, help="CFM prior temperature (0.0 to 1.0)")
    parser.add_argument("--solver", type=str, default="midpoint", choices=["midpoint", "rk4", "euler"], help="Numerical solver to use")
    parser.add_argument("--nfe", type=int, default=64, help="Number of function evaluations")
    parser.add_argument("--parallel_mode", action="store_true", help="Shuffle the audio paths and skip existing outputs")
    args = parser.parse_args()

    try:
        import torch
        import torchaudio
        from resemble_enhance.enhancer.inference import denoise, enhance
    except Exception:
        _log("ERROR: Could not import Resemble Enhance runtime dependencies.")
        traceback.print_exc()
        return 1

    device = args.device.lower().strip()
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        _log("CUDA is not available but --device is cuda; using CPU instead.")
        device = "cpu"
    if device not in {"cuda", "cpu"}:
        _log(f"Unknown device {args.device!r}; use cuda, cpu, or auto.")
        return 2

    _log("TTS Web UI Resemble direct runner active.")
    _log("This runner avoids packaged CLI pathlib/torchaudio issues and logs every major step.")
    _log(f"Input directory: {args.in_dir}")
    _log(f"Output directory: {args.out_dir}")
    _log(f"Mode: {'denoise_only' if args.denoise_only else 'enhance'}")
    _log(f"Device: {device}")
    _log(f"Suffix: {args.suffix}")
    if not args.in_dir.exists():
        _log(f"ERROR: input directory does not exist: {args.in_dir}")
        return 3
    args.out_dir.mkdir(parents=True, exist_ok=True)

    paths = sorted(args.in_dir.glob(f"**/*{args.suffix}"))
    if args.parallel_mode:
        random.shuffle(paths)
    _log(f"Input files discovered: {len(paths)}")
    if len(paths) == 0:
        _log(f"No {args.suffix} files found in the following path: {args.in_dir}")
        return 4

    start_time = time.perf_counter()
    written = []
    for idx, path in enumerate(paths, start=1):
        out_path = args.out_dir / path.relative_to(args.in_dir)
        if args.parallel_mode and out_path.exists():
            _log(f"[{idx}/{len(paths)}] Skipping existing output: {out_path}")
            written.append(out_path)
            continue
        try:
            _log(f"[{idx}/{len(paths)}] Loading audio: {path}")
            dwav, sr = torchaudio.load(str(path))
            _log(f"[{idx}/{len(paths)}] Loaded tensor shape={tuple(dwav.shape)} sample_rate={sr}")
            dwav = dwav.mean(0)
            if args.denoise_only:
                _log(f"[{idx}/{len(paths)}] Running denoise...")
                hwav, sr = denoise(dwav=dwav, sr=sr, device=device, run_dir=args.run_dir)
            else:
                _log(f"[{idx}/{len(paths)}] Running enhance solver={args.solver} nfe={args.nfe} lambd={args.lambd} tau={args.tau}...")
                hwav, sr = enhance(dwav=dwav, sr=sr, device=device, nfe=args.nfe, solver=args.solver, lambd=args.lambd, tau=args.tau, run_dir=args.run_dir)
            _log(f"[{idx}/{len(paths)}] Model returned shape={tuple(hwav.shape)} sample_rate={sr}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            _log(f"[{idx}/{len(paths)}] Saving output: {out_path}")
            torchaudio.save(str(out_path), hwav[None], sr)
            if not out_path.exists() or out_path.stat().st_size <= 0:
                _log(f"ERROR: save completed but output file is missing or empty: {out_path}")
                return 5
            _log(f"[{idx}/{len(paths)}] Output written: {out_path} ({out_path.stat().st_size} bytes)")
            written.append(out_path)
        except Exception:
            _log(f"ERROR while processing {path}")
            traceback.print_exc()
            return 1

    elapsed_time = time.perf_counter() - start_time
    _log(f"Enhancement done. {len(written)} files written in {elapsed_time:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

RESEMBLEWRAPPER
chmod +x "$LAB/engines/resemble-enhance/resemble_enhance_webui_wrapper.py"

cat > "$LAB/engines/resemble-enhance/resemble-enhance-webui" <<'RESEMBLELAUNCHER'
#!/usr/bin/env bash
set -euo pipefail
LAB="${TTS_LAB:-/home/user/tts-lab}"
ROOT="${TTS_RESEMBLE_ROOT:-$LAB/engines/resemble-enhance}"
ENV_NAME="${TTS_RESEMBLE_CONDA_ENV:-tts-resemble-enhance}"
WRAPPER="${TTS_RESEMBLE_COMPAT_WRAPPER:-$ROOT/resemble_enhance_webui_wrapper.py}"

if [[ -n "${TTS_RESEMBLE_PYTHON:-}" && -x "${TTS_RESEMBLE_PYTHON:-}" ]]; then
  PY="$TTS_RESEMBLE_PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif [[ -x "$HOME/miniconda3/envs/$ENV_NAME/bin/python" ]]; then
  PY="$HOME/miniconda3/envs/$ENV_NAME/bin/python"
elif [[ -x "$HOME/anaconda3/envs/$ENV_NAME/bin/python" ]]; then
  PY="$HOME/anaconda3/envs/$ENV_NAME/bin/python"
else
  echo "ERROR: Resemble Enhance Web UI launcher could not find an isolated env Python." >&2
  echo "Checked: $ROOT/.venv/bin/python, $HOME/miniconda3/envs/$ENV_NAME/bin/python, $HOME/anaconda3/envs/$ENV_NAME/bin/python" >&2
  exit 127
fi

if [[ ! -f "$WRAPPER" ]]; then
  echo "ERROR: Resemble Enhance Web UI runner not found: $WRAPPER" >&2
  exit 127
fi

exec "$PY" "$WRAPPER" "$@"
RESEMBLELAUNCHER
chmod +x "$LAB/engines/resemble-enhance/resemble-enhance-webui"

echo "Installed Resemble Enhance Web UI launcher: $LAB/engines/resemble-enhance/resemble-enhance-webui"

echo "Installed TTS Lab Unified Web UI v${APP_VERSION} to $WEBUI"
echo "Start with: $LAB/start-tts-webui.sh"
echo "Open: http://127.0.0.1:7870"
