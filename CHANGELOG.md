# Changelog

## v0.1.1-alpha - 2026-07-05

Public alpha confidence pass.

Includes:

- Web UI v0.86
- Maintenance stack-status card for the public launcher contract
- `/api/stack-status` diagnostics endpoint
- copyable stack diagnostics from the browser
- top-level Known Issues / alpha caveats section
- validated configuration notes in `docs/VALIDATED_CONFIGS.md`

Validation:

- Web UI Python syntax check passed.
- Web UI browser JavaScript parsed with Node.
- Temporary local server started with an isolated `TTS_LAB`.
- `/api/meta` returned Web UI version `0.86`.
- `/api/stack-status` returned useful missing-stack diagnostics instead of crashing.

## v0.1.0-alpha - 2026-07-05

Initial public alpha repository for HandAI TTS Lab.

Includes:

- Web UI v0.85
- TTS Lab Stack Installer v0.1.2
- MIT license
- local-only security guidance
- AI-assisted software development disclosure
- integration documentation for the separate HandAI Video Downloader helper

Validation before publication:

- Web UI Python syntax check passed.
- Web UI browser JavaScript parsed with Node.
- Web UI install script syntax check passed.
- Stack installer shell syntax check passed.
- Stack installer `--only-launchers` mode tested on target machine.
- Browser UI generated and played Chatterbox, Qwen3, and CosyVoice audio on the maintainer's RTX 2060 6GB laptop.
