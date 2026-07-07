# Changelog

## v0.1.2-alpha - 2026-07-07

AI Studio bridge pass.

Includes:

- Web UI v0.87
- optional HandAISpoke / AI Studio Bridge sidecar on `127.0.0.1:7871`
- token-protected bridge endpoints for status, clone-TTS patch requests, and job status
- bridge-side logging to `/home/user/tts-lab/logs/ui-diagnostics/ai-studio-bridge.log`
- bridge docs for API contract, Cloudflare quick-tunnel testing, and AI Studio helper code
- `.env.example` entries for bridge configuration without committing real tokens

Security / architecture notes:

- The full Web UI remains local and should not be exposed through Cloudflare.
- The bridge calls the existing Web UI `/api/generate` and `/api/jobs/<job_id>` APIs instead of duplicating synthesis logic.
- Gemini / Google AI Studio should not be described as voice cloning; local TTS engines perform cloned/custom voice generation.

Validation:

- Bridge Python syntax check passed.
- Bridge smoke-test client Python syntax check passed.
- Web UI Python syntax check passed.
- Web UI installer shell syntax check passed.
- Temporary Web UI server started with isolated `TTS_LAB`.
- Temporary bridge server started with a test token.
- Bridge status endpoint returned Web UI version `0.87` through token auth.
- Unauthorized bridge status request returned `401`.
- Clone-TTS endpoint completed against a fake local launcher that wrote a valid WAV, proving request → Web UI job → output → base64 response flow without heavy model inference.

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
