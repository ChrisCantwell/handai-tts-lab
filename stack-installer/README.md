# TTS Lab Stack Installer v0.1.2

Companion installer for the Audio/TTS/STT Web UI. It creates the local engine stack contract the UI expects:

```bash
/home/user/tts-lab/tts-lab.sh synth chatterbox --text "..."
/home/user/tts-lab/tts-lab.sh synth qwen3 --text "..." --x-vector-only
/home/user/tts-lab/tts-lab.sh synth cosyvoice --text "..."
```

This is intended for Ubuntu/Linux + NVIDIA GPU + Conda-style local installs. It was distilled from the Grok session that originally created the working local `/home/user/tts-lab` folder.

## AI-assisted software development

This project is intentionally documented as **AI-assisted software development**.

The human maintainer supplied the product direction, workflow requirements, real-machine testing, release judgment, and **descriptive design through ChatGPT**. ChatGPT assisted with implementation, refactoring, packaging, documentation, diagnostics, and changelog work. Grok/Grok Build assisted with portions of the original local TTS stack and helper tooling that this installer now distills into a cleaner, repeatable setup.

The result should be understood as maintainer-directed software built with AI collaborators, not as unattended autonomous code generation. Practical responsibility remains with the maintainer: features are tested against the local lab, logs are reviewed, and releases are accepted only after the maintainer confirms the workflow behaves as intended.

## What it installs

Default install:

- TTS Lab folders under `$HOME/tts-lab`
- Miniforge/Conda at `$HOME/miniconda3` if no conda exists there
- system packages where possible: `git`, `ffmpeg`, `sox`, `libsox-dev`, `espeak-ng`, `git-lfs`, `curl`, certificates
- HandAI Video Downloader from `https://github.com/ChrisCantwell/handai-videodownloader`
- root launcher: `$HOME/video-dl/video-dl`
- TTS launcher: `$HOME/tts-lab/tts-lab.sh`
- wrapper scripts under `$HOME/tts-lab/scripts/`
- Chatterbox-Turbo conda env: `tts-chatterbox`
- Qwen3-TTS 0.6B conda env: `tts-qwen3`
- CosyVoice 3 conda env: `tts-cosyvoice`

Optional:

- F5-TTS env: `tts-f5`, only with `--with-f5-experimental`

## Why F5 is optional

The original RTX 2060 setup session got Chatterbox, Qwen3, and CosyVoice working. F5 installed but hit dependency conflicts and later a SIGSEGV during generation. For that reason, this installer keeps F5 out of the default success path.

## Quick start

```bash
chmod +x install-tts-lab-stack.sh
./install-tts-lab-stack.sh --yes
```

Then check status:

```bash
$HOME/tts-lab/tts-lab.sh status
```

## Useful install modes

Install everything default and non-interactive:

```bash
./install-tts-lab-stack.sh --yes
```

Install video downloader only:

```bash
./install-tts-lab-stack.sh --only-video-dl --yes
```

Rewrite launchers only:

```bash
./install-tts-lab-stack.sh --only-launchers --yes
```

Skip model pre-downloads:

```bash
./install-tts-lab-stack.sh --no-model-downloads --yes
```

Run synthesis smoke tests if you already have a reference WAV at `$HOME/tts-lab/references/voice_ref.wav`:

```bash
./install-tts-lab-stack.sh --run-smoke-tests --yes
```

Install F5 as experimental:

```bash
./install-tts-lab-stack.sh --with-f5-experimental --yes
```

## Path overrides

```bash
TTS_LAB="$HOME/tts-lab" CONDA_ROOT="$HOME/miniconda3" VIDEO_DL_DIR="$HOME/video-dl" ./install-tts-lab-stack.sh --yes
```

Or CLI flags:

```bash
./install-tts-lab-stack.sh \
  --lab "$HOME/tts-lab" \
  --conda-root "$HOME/miniconda3" \
  --video-dl-dir "$HOME/video-dl" \
  --yes
```

## Web UI integration

The Web UI can call the downloader through:

```bash
/home/user/video-dl/video-dl {url} {out}
```

For current local usage:

```bash
TTS_VIDEO_DL_CMD='/home/user/video-dl/video-dl {url} {out}' ./start.sh
```

The stack installer also writes:

```bash
$HOME/tts-lab/stack-env.example
```

## Logs

Installer logs are written to:

```text
$HOME/tts-lab/logs/stack-installer/
```

## Important caveats

This is a first public/developer installer, not a polished consumer installer. Model packages are large, GPU stacks are fragile, and upstream packages may change.

The installer is deliberately verbose and log-heavy. When in doubt, inspect the newest log file under `logs/stack-installer/`.
