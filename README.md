# HandAI TTS Lab

HandAI TTS Lab is a local, browser-based audio production and AI voice/TTS/STT workstation. It combines a unified Web UI with a companion stack installer for local open-source voice engines and helper tools.

The project is designed around a practical local workflow:

```text
audio/video source
→ archive/download
→ extract/clean/enhance audio
→ transcribe
→ create references/profiles
→ synthesize speech
→ organize/manage outputs
```

Normal use is intended to happen in the browser. Terminal commands are acceptable for installation and debugging, but finished workflows should become UI actions with visible status, logs, and recoverable failures.

## Current alpha contents

This public alpha includes:

- **Web UI v0.88** in [`webui/`](webui/)
- **TTS Lab Stack Installer v0.1.2** in [`stack-installer/`](stack-installer/)
- Optional **HandAISpoke / AI Studio Bridge** sidecar for short local TTS voice patches
- Experimental **Speech Repair Analysis / diarization foundation** for speaker-aware transcripts and proposed edit decisions
- Documentation for the AI-assisted development process in [`docs/`](docs/)

The Web UI and stack installer are kept in separate folders so the app and the machine setup contract stay understandable without creating an extra repository.

## AI-assisted software development

This project is intentionally documented as **AI-assisted software development**.

The human maintainer supplied the product direction, workflow requirements, real-machine testing, release judgment, and **descriptive design through ChatGPT**. ChatGPT assisted with implementation, refactoring, packaging, documentation, diagnostics, and changelog work. Grok/Grok Build assisted with portions of the original local TTS stack and helper tooling.

The result should be understood as maintainer-directed software built with AI collaborators, not as unattended autonomous code generation. Practical responsibility remains with the maintainer: features are tested against the local lab, logs are reviewed, and releases are accepted only after the maintainer confirms the workflow behaves as intended.

## Repository layout

```text
handai-tts-lab/
  webui/                  Unified browser UI
  stack-installer/        Companion installer for local engine stack
  docs/                   Project notes and AI-assisted development disclosure
  README.md               Project overview
  CHANGELOG.md            Top-level release history
  LICENSE                 MIT license for this repository's code/docs
  SECURITY.md             Local-only security guidance
  .env.example            Example local environment settings; no real tokens
```

## Quick start

For a machine that already has a working `/home/user/tts-lab` launcher stack:

```bash
cd webui
chmod +x install.sh
./install.sh
```

Then start the UI with the command printed by the installer.

For a fresh or repair install of the local engine stack:

```bash
cd stack-installer
chmod +x install-tts-lab-stack.sh
./install-tts-lab-stack.sh --yes
```

Then verify:

```bash
$HOME/tts-lab/tts-lab.sh status
```

After installing Web UI v0.86, open **Maintenance / Repairs → TTS Lab stack contract** and click **Refresh stack status**. That browser-side diagnostic reports the detected launcher, engine envs, helper tools, video downloader, external-launch tools, and log paths without merging stack installation into the Web UI installer.

## What the Web UI expects

The Web UI calls a local launcher contract like this:

```bash
/home/user/tts-lab/tts-lab.sh synth chatterbox --text "..."
/home/user/tts-lab/tts-lab.sh synth qwen3 --text "..."
/home/user/tts-lab/tts-lab.sh synth cosyvoice --text "..."
```

The stack installer exists to create or repair that contract.

## Video downloader integration

Video Intake URL importing uses the separate HandAI Video Downloader helper:

```text
https://github.com/ChrisCantwell/handai-videodownloader
```

The stack installer can clone/install it at:

```text
$HOME/video-dl/video-dl
```

The Web UI can also be pointed at a custom downloader command with:

```bash
TTS_VIDEO_DL_CMD='/home/user/video-dl/video-dl {url} {out}' ./start.sh
```

Video Intake should remain archive-first: download/archive the source media first, then extract audio as a separate action.


## Speech Repair Analysis / diarization foundation

Web UI v0.88 adds a review-first analysis layer for spoken-word editing and podcast/archive transcription. It is designed to prepare the ground for filler removal, stutter cleanup, false-start review, and diarized archive transcripts.

The v0.88 analysis path can produce:

```text
source audio
→ Faster-Whisper transcript with word timestamps when available
→ speaker-aware transcript JSON
→ proposed filler/repetition/false-start cuts
→ Markdown transcript and proposed-cuts JSON
```

This is intentionally **not** a one-click destructive editor. Proposed cuts are review candidates. True WhisperX/pyannote diarization and CrisperWhisper verbatim transcription are documented as experimental backend targets, with status reporting in the STT tab.

See [`docs/speech-analysis-diarization.md`](docs/speech-analysis-diarization.md).

## HandAISpoke / AI Studio Bridge

Web UI v0.87 adds an optional local sidecar bridge for Google AI Studio / HandAISpoke speech-repair experiments.

```text
Google AI Studio / HandAISpoke
→ optional Cloudflare tunnel to 127.0.0.1:7871
→ token-protected local AI Studio bridge
→ TTS Web UI on 127.0.0.1:7870
→ local Chatterbox/Qwen3/CosyVoice engine
```

The bridge is disabled unless explicitly launched, binds to `127.0.0.1` by default, and requires `X-HandAISpoke-Bridge-Token` from `TTS_AI_STUDIO_BRIDGE_TOKEN`.

Do **not** tunnel the full Web UI. If Cloudflare is used for quick AI Studio testing, tunnel only the bridge port `7871`.

Correct wording: Gemini / Google AI Studio is not the voice-cloning engine. Local cloned/custom voice generation is handled by the configured local TTS engine.

See [`docs/ai-studio-bridge.md`](docs/ai-studio-bridge.md), [`docs/api-contract.md`](docs/api-contract.md), and [`docs/cloudflare-testing.md`](docs/cloudflare-testing.md).

## Tested local configuration

The current alpha path has been tested by the maintainer on an Ubuntu/Linux laptop with:

- NVIDIA RTX 2060 Max-Q
- 6GB VRAM
- local Conda environments
- a 9-second voice reference sample

Confirmed through the browser UI with generated and playable WAV output:

```text
Chatterbox: pass
Qwen3: pass
CosyVoice: pass with non-fatal CUDA-provider warnings
F5: present/experimental, not part of the green path
Video downloader: detected and working as separate helper
```

See [`docs/VALIDATED_CONFIGS.md`](docs/VALIDATED_CONFIGS.md) for the current validation notes.

## Known issues / alpha caveats

This is an alpha/developer project, not a polished consumer installer. GPU ML dependencies are fragile, model downloads are large, and upstream packages may change.

Known current caveats:

- F5 is present/experimental and should not be treated as part of the green path yet.
- Linux + NVIDIA GPU + Conda is the primary validated stack.
- Qwen3 may warn that `flash-attn` is not installed; that is expected to affect speed, not basic generation.
- CosyVoice may report CUDA-provider or `libcublasLt.so.11` warnings and still generate audio via fallback behavior.
- Large/long enhancement jobs can exceed available VRAM on 6GB GPUs.

Do **not** expose this local Web UI directly to the public internet. It can launch local processes, access files under the TTS Lab workspace, save tokens, run jobs, and open desktop applications.

## Third-party licenses and generated content

The MIT license in this repository covers this repository's code and documentation only. It does not change the licenses, model cards, terms, or usage restrictions of third-party engines, model weights, Python packages, media sources, or generated content processed with this software.

Users are responsible for complying with the licenses and terms of the tools, models, and media they install or invoke.
