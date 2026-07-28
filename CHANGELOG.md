## v0.97 - Chatterbox-Turbo controls and performance tags

- Hotfix: restores a per-line `text = spoken_text` compatibility alias so legacy batch-renderer references no longer raise `NameError` after successful parsing.

- Hotfix: corrects a Tagged Script batch `NameError` caused by a stale `text` progress-field reference after the parser moved to `spoken_text`.
- Hotfix: corrects over-escaped Python whitespace and word-boundary regexes that produced zero Tagged Script word counts despite successful line detection.
- Adds an isolated parser regression test covering inline styles, multi-line style blocks, and positional vocal events.

- Adds real Chatterbox-Turbo sampling controls: temperature, repetition penalty, top-p, top-k, reference loudness normalization, and optional seed.
- Leaves blank seed behavior random; queued takes may increment an entered seed for reproducible alternatives.
- Adds supported Turbo performance-style and vocal-event insertion tools.
- Parses standalone performance blocks and leading inline performance tags in Tagged Scripts while preserving positional vocal events.
- Validates unsupported, nested, mismatched, and unclosed performance tags before generation.
- Saves performance style and exact engine options in batch manifests, take metadata, output sidecars, and diagnostics.
- Adds lazy Take Manager overrides for style and Turbo sampling controls.
- Updates the generated machine-local launcher/helper so the Web UI controls reach the confirmed ChatterboxTurboTTS 0.1.7 API.
- Intentionally omits CFG, min-p, and exaggeration because Chatterbox-Turbo accepts but ignores them.

## v0.94.2 - Tagged Script Workspace refresh polish

## v0.95.5 - Jobs startup render budget

- Reduced startup/page-refresh stalls by rendering only a small recent-job window in the Jobs panel by default.
- Added Jobs panel controls to show 12 more jobs or return to fewer jobs.
- Lazy-rendered Tagged Script batch line/take details only when the batch-details panel is opened, avoiding hundreds of startup audio elements and action menus.
- Replaced the expensive Jobs refresh signature with a lightweight child/take count signature while preserving detailed Take Manager refresh behavior.
- Added UI diagnostics for slow Jobs renders and slow lazy batch-line renders.


## v0.95.4 - Initial-load Jobs render gate

- Fixed the remaining startup/page-refresh freeze after v0.95.3 by making hidden-Jobs render detection use the early `localStorage` boot preference before `/api/state` has filled the Options form.
- Prevented the first `/api/jobs` refresh from rendering the full hidden Jobs pane when Jobs are configured as a separate tab.
- Added a one-time UI diagnostic log entry when hidden Jobs rendering is skipped during startup/polling.


## v0.95.3 - UI performance / boot layout

- Saved Jobs-as-tab/layout preferences in browser localStorage so the chosen layout paints immediately on reload before `/api/state` returns.
- Cached the latest Jobs payload for Take Manager tab activation instead of forcing an immediate duplicate `/api/jobs` fetch.
- Stopped rendering hidden Jobs DOM when Jobs are configured as a tab and the Jobs tab is not visible.
- Stopped rendering the hidden Take Manager on every job poll; it now auto-renders only while the Take Manager tab is visible.
- Avoided full layout reapplication while rendering Take Manager content, reducing unnecessary DOM movement.


## v0.95.2 - Take Manager tab

- Added a dedicated Take Manager tab for completed Tagged Script batch repair.
- Added a Send to Take Manager button on batch job cards.
- Added a completed-batch dropdown and refresh control inside the Take Manager tab.
- Kept the Take Manager synchronized while job polling updates alternate takes and selected-take state.
- Added clearer top-level status after queueing alternate takes or selecting a take for mixdown.


## v0.95.1 - Take Manager click/status fix

- Fixed malformed inline Take Manager click handlers that could throw `Uncaught SyntaxError: Unexpected end of input` when generating alternate takes.
- Added immediate visible status and UI diagnostics when Generate alternate take or Use this take in mixdown is clicked.


## v0.95 - Tagged Script Take Manager

- Added per-line alternate-take management for completed Tagged Script batches.
- Added one-line regeneration with editable text, engine override, profile override, and Qwen x-vector toggle.
- Added selected-take tracking so rebuilt mixdowns use the chosen performance for each line.
- Added backend manifest take metadata with future-ready `engine_options` fields for later engine-specific style controls.
- Updated Jobs rendering and refresh signatures so new takes and selected-take changes appear without confusing stale UI.


- Changed the Tagged Script Workspace refresh button so it reports `Refreshed projects, scripts, casts.` after a successful manual refresh.
- Prevented the stale previous workspace status message, such as `Saved project`, from remaining visible after refresh.

## v0.94.1 - Tagged Script Workspace polish

- Added independent names for saved scripts, casts, and projects in the Tagged Script Workspace panel.
- Changed script and cast saving so they do not inherit the project name by default.
- Preserved optional script/cast display names inside saved project JSON.
- Improved historical-output recovery by skipping internal Tagged Script silence/intermediate mixdown WAV helpers.
- Added clearer recovered-job labels for Tagged Script mixdowns and generic recovered outputs.

## v0.94 - Tagged Script Workspace

- Adds Tagged Script Workspace save/load controls.
- Saves scripts, casts, and full projects separately so unfinished scripts and reusable casts can be preserved.
- Adds browser upload for `.txt` / `.md` scripts and cast/project JSON.
- Stores workspace files under `/home/user/tts-lab/projects/tagged-script/`.
- Preserves project script text, role map, default engine, and mixdown settings.

## v0.93.3 - Post-run Mixdown Backend Fix

- Fixes post-run Tagged Script mixdown jobs that were queued from legacy completed batch cards without a manifest filesystem path.
- Adds a backend override that accepts source job IDs and recovers rendered line files from job children, manifest URLs/paths, or batch output directory scanning.
- Keeps the operation non-destructive: existing TTS line files are reused and not re-rendered.

## v0.93.2 - Legacy Batch Mixdown Visibility

- Fixes post-run Tagged Script mixdown controls not appearing on older completed batch jobs with manifest/child line outputs but no top-level assembled audio.
- Adds a defensive `/api/batch/mixdown` backend path and `batch-mixdown` job type when missing.
- Provides a direct `Mix down this completed batch` panel on eligible batch job cards.

## v0.93.1 - Tagged Script Hotfix

- Strip BOM and zero-width Unicode marker characters before Tagged Script backend parsing.
- Add browser-side Tagged Script preflight warnings for invisible characters, detected roles, unmapped roles, and Qwen3 fallback risk.
- Add post-run mixdown support for completed or partial Tagged Script batch jobs without re-rendering TTS lines.
- Add `/api/batch/mixdown` and a `batch-mixdown` job kind for assembling existing batch line outputs.
- Update Jobs cards with a **Mix down this completed batch** control when a batch manifest and successful line outputs are available.

## v0.93 - Tagged Script Production Feedback / ETA / Mixdown

- Added inline queue/running/done/error feedback for Synthesize → Generate.
- Added inline queue/running/done/error feedback for Tagged Script → Generate tagged script.
- Added live elapsed/waiting/runtime timers to Jobs cards.
- Added Tagged Script progress by lines, words, and weighted units.
- Added rough ETA for Tagged Script batches after enough line work has completed.
- Added Tagged Script Assembly / mixdown controls.
- Preserved per-line outputs while optionally producing one final full-script WAV or MP3.
- Added configurable pause between generated tagged-script lines.
- Added batch job result metadata for progress and final assembled files.

## v0.92 - Tagged Script Role Map Builder

- Added a visual role-map builder above the Tagged Script JSON field.
- Script role names are now explicitly independent from saved voice-profile names.
- Added dropdown selection for saved voice profiles per role.
- Added per-role engine selection and Qwen x-vector-only toggle.
- Added Add Role, Auto-detect roles from script, Sync builder from JSON, and Apply builder to JSON controls.
- Preserves the advanced JSON escape hatch and unknown role config fields where possible.
- Saves role-map JSON in the remembered form state.

## v0.91 - Local Speech API / AI Studio Bridge STT

- Added internal Local Speech API routes for Faster-Whisper and WhisperX:
  - `GET /api/speech/status`
  - `GET /api/speech/engines`
  - `POST /api/speech/upload`
  - `POST /api/speech/transcribe`
  - `GET /api/speech/jobs/<job_id>`
- Added AI Studio bridge STT routes so Cloudflare can expose only the bridge, not the full Web UI:
  - `POST /api/ai-studio-bridge/transcribe`
  - `POST /v1/audio/transcriptions`
- Added OpenAI-compatible multipart transcription support for coding assistants and app previews.
- Added native async transcription flow for long files.
- Added normalized speech JSON output under `/home/user/tts-lab/output/speech_api/`.
- Kept `/api/ai-studio-bridge/clone-tts` unchanged.
- Kept CrisperWhisper hidden/unsupported because local smoke testing showed stability problems.

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
