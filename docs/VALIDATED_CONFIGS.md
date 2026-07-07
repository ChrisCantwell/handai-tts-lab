# Validated Configurations

This file records configurations that have actually been exercised, not theoretical compatibility claims.

## Maintainer laptop green path

Validated by the maintainer on July 5, 2026.

```text
OS: Ubuntu/Linux
GPU: NVIDIA RTX 2060 Max-Q
VRAM: 6GB
Environment manager: Conda / Miniconda-style envs
Reference sample: 9-second WAV
Web UI: v0.85 during publication validation, v0.86 diagnostics smoke-tested afterward
Stack Installer: v0.1.2
Video downloader helper: handai-videodownloader
```

Confirmed browser/UI generation and playback:

```text
Chatterbox: PASS
Qwen3: PASS
CosyVoice: PASS
Video downloader helper: detected / working
F5: present but experimental; not green path
```

Known non-fatal warnings seen on this family of setup:

```text
Qwen3: flash-attn not installed; expected slower inference only.
CosyVoice: onnxruntime CUDA provider / libcublasLt.so.11 warning; fallback still generated audio.
CosyVoice: prompt text longer than synthesis text warning; not treated as installer failure.
```

## Web UI v0.86 diagnostics smoke test

Performed in a sandbox container without the heavy TTS stack installed.

Validated:

```text
python3 -m py_compile webui/tts_webui.py
node --check extracted browser JavaScript
start server with isolated TTS_LAB
GET /api/meta
GET /api/stack-status
```

Expected result in the sandbox:

```text
/api/meta reports version 0.86.
/api/stack-status reports missing launcher/envs as diagnostics, not as a server crash.
```

## Compatibility claim

The current public alpha should be described as tested on the maintainer's Ubuntu/NVIDIA/Conda laptop and designed for similar local Linux systems. Other operating systems, CPU-only machines, AMD GPUs, and substantially different Conda/CUDA stacks are not yet validated.
