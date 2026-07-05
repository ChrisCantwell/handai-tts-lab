# TTS Stack Install Notes

## Contract created for the Web UI

The Audio/TTS/STT Web UI currently expects a launcher compatible with:

```bash
$TTS_LAB/tts-lab.sh synth ENGINE --text TEXT [--ref PATH] [--out PATH]
```

The default path is:

```text
/home/user/tts-lab/tts-lab.sh
```

The generated launcher supports:

```text
chatterbox
qwen3
cosyvoice
f5 experimental only
```

It also supports:

```bash
tts-lab.sh video-dl URL OUT_DIR
tts-lab.sh status
tts-lab.sh test [engine]
tts-lab.sh env ENGINE
```

## Engine status from source session

The installer was based on the Grok session that created the original local lab. Final practical outcome from that session:

- Chatterbox: working
- Qwen3: working
- CosyVoice: working after dependency fixes and one-engine-at-a-time testing
- F5: not reliable; dependency conflicts and SIGSEGV during generation

## HandAI Video Downloader

The video downloader is now treated as an external helper dependency, not bundled into the Web UI.

Default repo:

```text
https://github.com/ChrisCantwell/handai-videodownloader
```

Default installed path:

```text
/home/user/video-dl
```

Expected executable:

```text
/home/user/video-dl/video-dl
```

Supported call form:

```bash
/home/user/video-dl/video-dl URL OUT_DIR
```

Recommended Web UI command template:

```bash
TTS_VIDEO_DL_CMD='/home/user/video-dl/video-dl {url} {out}' ./start.sh
```

## Why this is separate from the Web UI installer

The Web UI installer should remain light and focused on the browser app. The stack installer owns large model dependencies, Conda environments, GPU package choices, and helper tools.

Recommended architecture:

```text
Web UI installer:
  install/repair UI
  detect tts-lab.sh
  detect video-dl
  show missing pieces in Maintenance

Stack installer:
  install Conda/envs/models
  create tts-lab.sh
  install video downloader
  write logs
```

## First debugging commands

```bash
$HOME/tts-lab/tts-lab.sh status
ls -lt $HOME/tts-lab/logs/stack-installer | head
nvidia-smi
```

Video downloader:

```bash
$HOME/video-dl/video-dl --help
$HOME/tts-lab/tts-lab.sh video-dl 'https://www.youtube.com/watch?v=Ic-wMMTCeEY' /tmp/video-dl-test
```

Chatterbox smoke test:

```bash
$HOME/tts-lab/tts-lab.sh synth chatterbox --text 'Hello from the local TTS lab.'
```

Qwen3 smoke test:

```bash
$HOME/tts-lab/tts-lab.sh synth qwen3 --text 'Status update.' --x-vector-only
```
