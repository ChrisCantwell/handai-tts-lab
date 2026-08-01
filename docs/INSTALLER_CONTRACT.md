# HandAI TTS Lab Installer Contract

Version: 0.2.0  
Date: 2026-08-01  
Status: Approved — v1 scope locked

## 1. Purpose

This document defines what the HandAI TTS Lab installer must do, what it must preserve, and what it must not do. It exists so that installer work can be scoped, reviewed, and handed off without re-discovering the current scattered layout.

## 2. Goals

- Install HandAI TTS Lab from the GitHub repository onto a fresh Linux system.
- Produce a self-contained application directory at `~/handai-tts-lab/` by default.
- Separate replaceable application code from precious user data.
- Support GPU detection and install engines conditionally based on available VRAM.
- Provide working Chatterbox and Whisper smoke tests at the end of installation.
- Allow backup/restore of workspace data and model caches.

## 3. Non-Goals

- Windows support in v1.
- Engine redesigns or swaps.
- Direct writes to the repository's `main` branch by the installer.
- Automatic cloud deployment templates (Runpod, AWS, etc.) in v1 — manual Runpod setup is acceptable.
- Full XDG Base Directory support. The contract documents the override, but v1 targets the self-contained `~/handai-tts-lab/` layout only.

## 4. Target Environment

- **OS:** Ubuntu 22.04/24.04 or compatible Debian-derived Linux. Other distros are best-effort.
- **CPU:** x86_64. ARM is out of scope for v1.
- **GPU:** NVIDIA GPU strongly recommended. CUDA 12.x support required.
- **RAM:** 16 GB minimum, 32 GB recommended.
- **VRAM tiers:**
  - **Minimum:** 6 GB — Chatterbox only, with possible CPU fallback for some engines.
  - **Recommended:** 12 GB+ — Chatterbox, Qwen3, CosyVoice green path.
  - **High-end:** 24 GB+ — F5-TTS becomes available as an opt-in experimental engine.
- **Storage:** 50 GB free minimum; 100 GB+ recommended if model caches are kept locally.
- **Network:** Broadband required for downloading conda, Python packages, and Hugging Face models.

## 5. Directory Layout

Default install root: `~/handai-tts-lab/`

```text
~/handai-tts-lab/
  ├── app/                    # Cloned repo or release files (replaceable on upgrade)
  │     ├── webui/            # tts_webui.py, stt_faster_whisper.py, tts_ai_studio_bridge.py
  │     ├── stack-installer/  # install-tts-lab-stack.sh and helpers
  │     ├── tools/            # backup-workspace.sh, etc.
  │     └── docs/
  ├── data/                   # User data (must be preserved across upgrades/reinstalls)
  │     ├── output/           # Generated audio, batches, manifests, mixdowns, job_history
  │     ├── projects/         # Tagged scripts, casts, projects
  │     ├── references/       # voice_ref.wav and profiles
  │     └── config/           # webui_state.json, huggingface_token, secrets
  ├── models/                 # Downloaded weights and caches
  │     ├── huggingface/      # ~/.cache/huggingface equivalent
  │     └── torch/            # ~/.cache/torch equivalent
  ├── backups/                # Output of backup-workspace.sh
  ├── engines/                # Engine-specific non-conda artifacts (e.g., resemble-enhance wrappers)
  ├── logs/                   # Installer and runtime logs
  ├── tmp/                    # Ephemeral working files
  ├── tts-lab.sh              # Main engine launcher
  ├── start-tts-webui.sh      # Start the web UI
  └── start-ai-studio-bridge.sh  # Optional bridge sidecar
```

### Environment variables

The installer and runtime use these variables, all defaulting to subdirectories of `TTS_LAB`:

- `TTS_LAB` — application root. Default: `~/handai-tts-lab`.
- `TTS_APP_DIR` — code location. Default: `$TTS_LAB/app`.
- `TTS_DATA_DIR` — user data root. Default: `$TTS_LAB/data`.
- `TTS_MODEL_DIR` — model cache root. Default: `$TTS_LAB/models`.
- `TTS_OUT` — output directory. Default: `$TTS_DATA_DIR/output`.
- `TTS_REF` — references directory. Default: `$TTS_DATA_DIR/references`.
- `TTS_JOB_DIR` — job history. Default: `$TTS_OUT/job_history`.
- `TTS_TAGGED_WORKSPACE_DIR` — tagged script projects. Default: `$TTS_DATA_DIR/projects/tagged-script`.
- `TTS_CONFIG_DIR` — config and secrets. Default: `$TTS_DATA_DIR/config`.
- `CONDA_ROOT` — conda installation root. Default: `~/miniconda3`.

### XDG override

For users who prefer the XDG Base Directory Specification, the installer respects `XDG_DATA_HOME` and `XDG_CONFIG_HOME` when `TTS_LAB_USE_XDG=1` is set. In that mode:

- Data goes to `$XDG_DATA_HOME/handai-tts-lab/` (default `~/.local/share/handai-tts-lab/`).
- Config/secrets go to `$XDG_CONFIG_HOME/handai-tts-lab/` (default `~/.config/handai-tts-lab/`).
- The application code still lives in `TTS_APP_DIR`.

## 6. Components to Install

### 6.1 System dependencies

The installer may install or check for:

- `git`
- `ffmpeg`
- `sox`
- `espeak-ng`
- `git-lfs`
- `curl`
- `wget`
- `build-essential`
- NVIDIA drivers and CUDA toolkit (or relies on Runpod/base image having them)

System dependency installation is gated by `--skip-system-deps` for users who manage packages themselves.

### 6.2 Conda

If `conda` is not found at `CONDA_ROOT` or on `PATH`, the installer downloads and installs Miniconda3 to `CONDA_ROOT`.

### 6.3 Conda environments

| Environment | Engine | Default | VRAM requirement | Notes |
|-------------|--------|---------|------------------|-------|
| `tts-chatterbox` | Chatterbox | Yes | 6 GB+ | Primary green-path engine. |
| `tts-qwen3` | Qwen3-TTS 0.6B | Yes | 8 GB+ | Green path; supports x-vector-only mode. |
| `tts-cosyvoice` | CosyVoice | Yes | 8 GB+ | Green path. |
| `tts-whisper` | Faster-Whisper STT | Yes | 6 GB+ | Required for STT features. |
| `tts-resemble-enhance` | Resemble Enhance | No | 8 GB+ | Optional audio enhancement. |
| `tts-f5` | F5-TTS | No | 24 GB+ | Opt-in experimental; known SIGSEGV risk on 6 GB. |
| `tts-whisperx` | WhisperX | No | 8 GB+ | Optional speech analysis / diarization. |
| `tts-crisperwhisper` | CrisperWhisper | No | 8 GB+ | Optional speech analysis. |
| `tts-ai-studio-bridge` | Bridge sidecar | Yes | Minimal | Required if using HandAISpoke integration. |

The installer detects available VRAM and **warns + prompts for confirmation** before skipping engines that may not fit. It does not silently skip engines. The user may override with flags such as `--with-f5-experimental` or `--skip-qwen3`.

### One-line install entrypoint

For convenience, a top-level `stack-installer/install.sh` script is provided. It can be run directly from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/ChrisCantwell/handai-tts-lab/main/stack-installer/install.sh | bash
```

This script:
1. Clones or updates the `handai-tts-lab` repo into `TTS_APP_DIR`.
2. Runs `stack-installer/install-tts-lab-stack.sh` to create conda envs, install engines, and download models.
3. Runs `webui/install.sh` to copy Python files and write start scripts.
4. Runs smoke tests and prints a summary.

Advanced users may skip the one-liner and clone the repo first, then run `stack-installer/install-tts-lab-stack.sh` directly.

### 6.5 Helper tools

- **HandAI Video Downloader:** cloned from `https://github.com/ChrisCantwell/handai-videodownloader` into `TTS_LAB/tools/video-dl` (or a configurable path).
- **Backup tool:** `tools/backup-workspace.sh` is available in the repo and usable immediately after clone.

### 6.6 Models and caches

The installer eagerly downloads required models for enabled engines, storing them under `TTS_MODEL_DIR/huggingface/` and `TTS_MODEL_DIR/torch/`:

- **Chatterbox:** eagerly downloaded so the TTS smoke test passes.
- **Faster-Whisper:** eagerly downloads at least one Whisper model so STT works out of the box.
- Other engines: models downloaded if the engine is installed and `--no-model-downloads` is not set.

A Hugging Face token is prompted if needed.

## 7. Secrets and Credentials

The installer must handle secrets without embedding them in code or logs:

- **Hugging Face token:** prompted or read from `HF_TOKEN` env var. Stored in `TTS_CONFIG_DIR/huggingface_token` with mode `0600`.
- **AI Studio bridge token:** generated automatically with `secrets.token_urlsafe(32)` if not provided. Stored in `TTS_CONFIG_DIR/ai_studio_bridge_token` with mode `0600` and written to `.env` files for the bridge.
- No secrets are committed to the repository.

## 8. Installation Modes (v1 scope)

### 8.1 Fresh install

Default mode. Creates `TTS_LAB`, installs conda if needed, creates environments, downloads models, copies code, writes start scripts, and runs smoke tests.

### 8.2 Upgrade / Repair / Uninstall (future)

Out of scope for v1. Reserved for later passes:

- **Upgrade:** replace `app/` with new release, preserve `data/` and `models/`, re-run stack installer for new dependencies.
- **Repair:** recreate missing/broken conda envs, re-download missing models, validate manifests.
- **Uninstall:** remove `TTS_LAB` and conda envs (with confirmation and backup prompt).

## 9. Data Preservation Rules

- The installer must never delete `data/` or `models/` during a fresh install unless explicitly confirmed by the user.
- Existing `output/`, `projects/`, `references/`, and `config/` directories must be detected and preserved if present.
- Model caches must be reused if they already exist at `TTS_MODEL_DIR/`.
- Installer logs are written to `TTS_LAB/logs/stack-installer/`.

## 10. Smoke Tests and Acceptance Criteria

At minimum, a successful install must:

1. Start the web UI without errors on `http://127.0.0.1:7870`.
2. Report all default-installed engines as available in the UI status panel.
3. Run a Chatterbox synthesis test and produce a valid WAV file.
4. Run a Faster-Whisper transcription test on a short generated WAV and produce a transcript.
5. Allow creating/importing a tagged script and rendering at least one line.
6. Write job history and output files to `TTS_DATA_DIR/output/`.

## 11. Boundaries

- The installer installs the application as it exists in the repository. No engine swaps.
- Engine additions (e.g., new TTS models) are out of scope for v1; the contract can be amended later.
- The installer does not configure reverse proxies, SSL, or public exposure.
- The installer does not set up continuous backup jobs; it only provides the backup tool.

## 12. Roadmap (post-v1)

- Full XDG Base Directory support (`TTS_LAB_USE_XDG=1`).
- Upgrade, repair, and uninstall modes.
- systemd user service for auto-start.
- Optional lazy model downloads with on-demand UI installation.

## 13. Open Decisions

1. Should the installer set up a systemd user service for auto-starting the web UI?
2. How should the installer validate CUDA/driver compatibility before installing GPU packages?
3. Should the web UI itself grow on-demand model downloads, or remain eager-only for v1?

## 13. Related Files

- `stack-installer/install-tts-lab-stack.sh` — existing engine-stack installer.
- `webui/install.sh` — existing web UI file-copier and start-script writer.
- `tools/backup-workspace.sh` — workspace and model backup tool.
- `docs/TTS_STACK_INSTALL.md` — notes from the original Grok session.
