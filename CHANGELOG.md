# Changelog

## v0.1.3-alpha patch 5 - 2026-07-08

WhisperX maintenance setup pass.

Includes:

- Web UI v0.90
- Maintenance status card for the isolated WhisperX speech-repair backend
- queued Install / repair WhisperX job
- queued WhisperX short-sample smoke-test job
- app-owned WhisperX JSON helper writer
- explicit separation from the existing faster-whisper STT environment
- no Speech Analysis integration yet; this pass only installs, repairs, detects, and smoke-tests the backend

Validation:

- Web UI Python syntax check should pass.
- Shell syntax checks should pass.
- Existing WhisperX installs should be detected without reinstalling.




## v0.1.3-alpha patch 3 - 2026-07-07

Metadata tab pass.

Includes:

- Web UI v0.89
- new Metadata tab for practical MP3 publishing cleanup
- upload MP3 + upload cover image workflow
- optional title, artist, album, year/date, genre, and comment fields
- FFmpeg-based ID3/cover-art embedding into a new MP3 copy
- original MP3 and image are preserved under the metadata work area
- output MP3 is saved under `/home/user/tts-lab/output/metadata/`
- completed metadata jobs appear in Jobs with playback/download/actions
- Metadata local saves follow the app-wide file naming defaults unless an output filename override is filled
- optional Download tagged MP3 checkbox for browser download/Save As workflows

Notes:

- This pass does not overwrite the source MP3.
- FFmpeg is required for the first metadata backend.
- This is intentionally simpler than Kid3/eyeD3: pick MP3, pick image, write a tagged copy.

Validation:

- Web UI Python syntax check should pass.
- Shell syntax checks should pass.


## v0.1.3-alpha patch 2 - 2026-07-07

Speech analysis editing handoff helper pass.

Includes:

- Web UI v0.88.2
- Audacity label export/copy helper for review-only speech-analysis cuts
- end-to-beginning edit checklist copy helper for manual editing
- preserved non-destructive speech analysis behavior
- current speech-analysis result caching so handoff buttons use the full cut list, not just the visible preview
- local queued/running/done/failure status beside the Analyze button for Jobs-as-tab layouts
- safer Audacity label export with short tab-delimited labels only
- Audacity labels omit the trailing blank line so Audacity does not warn about an incomplete extra label

Notes:

- This pass still does not cut audio automatically.
- Audacity labels and edit checklists are handoff aids for manual review.
- Audacity label output intentionally uses short plain labels to reduce importer fragility.
- Operators should still listen around each proposed region before deleting audio.

Validation:

- Web UI Python syntax check should pass.
- Browser JavaScript should parse with Node.

## v0.1.3-alpha patch - 2026-07-07

Speech analysis cut-consolidation hotfix.

Includes:

- Web UI v0.88.1
- consolidation of heavily overlapping `possible_false_start` candidates
- raw/suppressed candidate counts in speech analysis summaries
- regression test based on a real noisy repeated-take sample
- tighter false-start boundaries so common repeated phrases do not pull clean lead-in material into a proposed cut
- copy/select-all controls for the speech analysis JSON/result box

Notes:

- False-start candidates remain review-only and are never auto-cut.
- This pass does not add true WhisperX/pyannote diarization yet.

Validation:

- Web UI Python syntax check passed.
- Speech analysis candidate regression test passed.

## v0.1.3-alpha - 2026-07-07

Speech analysis and diarization foundation pass.

Includes:

- Web UI v0.88
- Speech Repair Analysis controls in the STT tab
- word-timestamp support in the Faster-Whisper helper for analysis jobs
- speaker-aware transcript JSON schema with `speaker`, `speaker_label`, and speaker-turn fields
- proposed edit-decision output for filler words, repeated words, and possible false starts
- analysis artifacts under `/home/user/tts-lab/output/speech_analysis/`
- backend status reporting for CrisperWhisper, WhisperX, pyannote, and auto-editor readiness
- documentation for diarization limitations and future speaker-label workflow

Notes:

- v0.88 does not cut audio destructively. It produces reviewable analysis JSON and proposed cuts.
- True WhisperX/pyannote diarization is treated as experimental/planned unless the backend is installed and wired in a later pass.
- Automatic speaker labels are placeholders. Human review is required before publishing or archive indexing.

Validation:

- Web UI Python syntax check passed.
- Faster-Whisper helper Python syntax check passed.
- Browser JavaScript parsed with Node.
- Speech analysis candidate-detection tests passed.

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
