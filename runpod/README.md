# HandAI TTS Lab - Runpod installer

Runpod-specific installer and repair tools for [handai-tts-lab](https://github.com/ChrisCantwell/handai-tts-lab).

## Quick start on a new Runpod pod

From inside the pod (SSH or Jupyter terminal):

```bash
curl -fsSL https://raw.githubusercontent.com/ChrisCantwell/handai-tts-lab/main/runpod/install-runpod.sh | bash
```

Or clone the repo and run locally:

```bash
git clone https://github.com/ChrisCantwell/handai-tts-lab.git /workspace/handai-tts-lab-app
cd /workspace/handai-tts-lab-app/runpod
./install-runpod.sh
```

Defaults:

- `TTS_LAB=/workspace/handai-tts-lab`
- `CONDA_ROOT=/workspace/miniconda3`
- `VIDEO_DL_DIR=/root/video-dl`

Default engines installed: **Chatterbox**, **Qwen3-TTS**, **CosyVoice**, **Faster-Whisper**. Optional engines (`--with-f5-experimental`, `--with-whisperx`, `--with-crisperwhisper`) are skipped unless requested.

### One-liner with optional engines

```bash
curl -fsSL https://raw.githubusercontent.com/ChrisCantwell/handai-tts-lab/main/runpod/install-runpod.sh | bash -s -- --with-whisperx --with-crisperwhisper --with-f5-experimental
```

## What the installer does

1. Clones/updates the `handai-tts-lab` repo into `/workspace/handai-tts-lab/app`.
2. Runs the stack installer with Runpod-aware paths and redirects pip cache/temp to `/workspace` so the 10 GB root overlay doesn't fill up.
3. Verifies every conda environment by importing the Python `encodings` module; reinstalls any broken/migrated environments without rebuilding the whole stack.
4. Bundles a static `ffmpeg`/`ffprobe` build into `/workspace/handai-tts-lab/bin/` and prepends it to `PATH` in the launcher scripts (Runpod base images lack ffmpeg).
5. Writes a standalone `/workspace/handai-tts-lab/repair-runpod-envs.sh` helper so repair works even if the repo's `runpod/` directory isn't populated yet.
6. Installs a systemd user service `tts-webui-runpod` that auto-starts the Web UI (may require a lingering user session on some pods).
7. Prints access instructions.

## Access the Web UI

### Option A: Local SSH tunnel (recommended)

On your local machine:

```bash
ssh -N -L 9090:127.0.0.1:7870 -p <runpod-ssh-port> root@<runpod-ip>
```

Then open `http://localhost:9090/` in your browser.

### Option B: Runpod proxy

Expose port `7870` in the Runpod template and use the proxy URL shown in the Runpod dashboard.

### Option C: Cloudflare quick tunnel (advanced)

Run a Cloudflare tunnel on the pod pointing to `127.0.0.1:7870`. This avoids opening the full Web UI port publicly without authentication.

## Repair after migration

Runpod migrations can leave conda environment directories empty while keeping their names in `conda env list`. This breaks `tts-lab.sh` and the Web UI backend.

To repair a migrated pod:

```bash
/workspace/handai-tts-lab/repair-runpod-envs.sh
```

Or:

```bash
cd /workspace/handai-tts-lab/app/runpod
./install-runpod.sh --repair
```

The repair script detects environments whose `lib/pythonX.Y` directory is empty or whose `python` cannot import `encodings`, removes them, and reinstalls only those engines.

## Files

- `install-runpod.sh` — full installer for new pods.
- `repair-runpod-envs.sh` — standalone repair script for migrated pods.
- `check_envs.sh` — quick health check for base conda and all engines.
- `README.md` — this file.

## Notes

- `/workspace` on Runpod is a network filesystem. It is persistent but not always fully synced during migrations. Active environments (ones that were recently used) usually survive; idle environments may need repair.
- The Web UI service runs under the current user's systemd user session. Runpod persistent pods usually preserve user sessions; if not, the repair script also restarts the service.
- For CI/automation, the installer accepts all stack-installer flags after the Runpod defaults are applied.
- The 10 GB root overlay (`/`) can fill quickly with pip cache and temp files. The installer sets `PIP_CACHE_DIR=/workspace/.pip-cache` and `TMPDIR=/workspace/tmp` to avoid this.
