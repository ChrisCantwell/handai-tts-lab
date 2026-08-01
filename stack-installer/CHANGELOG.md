# Changelog

## v0.1.2

- Adds explicit README language identifying the project as AI-assisted software development.
- Credits maintainer-directed descriptive design through ChatGPT, ChatGPT implementation/documentation help, and Grok/Grok Build contributions to the original local stack/helper tooling.
- Clarifies that releases remain maintainer-reviewed and tested, not unattended autonomous code generation.



## v0.1.1 - 2026-07-05

### Fixed
- Qwen3 launcher now defaults to `--x-vector-only` mode when no `--ref-text` is supplied, matching the simple Web UI/launcher use case.
- Qwen3 wrapper now also self-selects x-vector-only mode for direct calls without a reference transcript.
- CosyVoice wrapper now avoids `torchaudio.save` and writes PCM16 WAV with `wave` + `numpy` to reduce native-library segfault risk.
- CosyVoice launcher treats a non-zero process exit as a teardown warning if the output WAV was successfully written.

### Notes
- Chatterbox smoke test passed on the target RTX 2060 Max-Q system.
- Qwen3 previously failed because ICL mode requires `ref_text`; this version avoids that failure for default/simple calls.
- CosyVoice previously synthesized audio but segfaulted before/around file save; this version is designed to preserve the rendered audio where possible.

## v0.1.0

Initial companion stack installer.

- Creates TTS Lab folder structure.
- Installs/checks Conda.
- Installs/checks system dependencies.
- Installs HandAI Video Downloader from its public GitHub repo.
- Writes `/tts-lab.sh` launcher contract expected by the Web UI.
- Writes wrapper scripts for Chatterbox, Qwen3-TTS, CosyVoice, and experimental F5.
- Installs Chatterbox, Qwen3, and CosyVoice by default.
- Keeps F5 optional behind `--with-f5-experimental` because the original setup hit SIGSEGV.
- Adds status command and installer logs.
