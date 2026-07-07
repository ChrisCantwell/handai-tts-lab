# TTS Lab Unified Web UI v0.88.2

Local web UI for `/home/user/tts-lab` voice/TTS/STT/audio-production workflows. v0.88.2 turns Speech Repair Analysis into a more useful manual-editing handoff by adding Audacity labels and end-to-beginning edit checklists, while preserving the v0.88.1 cut-consolidation work, v0.87 AI Studio Bridge, v0.86 stack diagnostics, and v0.85 Actions dropdown/external launch work.

A dependency-light local web dashboard for the voice/TTS stack Grok installed under `/home/user/tts-lab`.

It does **not** merge the model environments. It calls the existing wrapper:

```bash
/home/user/tts-lab/tts-lab.sh synth <engine> ...
```

That keeps Chatterbox, Qwen3, CosyVoice, and F5 isolated in their own conda environments.

## Install / upgrade

This ZIP filename is versioned, but the folder inside the ZIP is intentionally unversioned for repeatable install commands.

```bash
unzip -o tts_unified_webui_v0.88.2.zip
cd tts_unified_webui
./install.sh
```

Start the UI:

```bash
/home/user/tts-lab/start-tts-webui.sh
```

Open:

```text
http://127.0.0.1:7870
```

## Optional STT / Faster-Whisper setup

The web UI includes the transcription helper, but the heavier Faster-Whisper environment is optional and is not reinstalled automatically during every web UI upgrade.

Install Faster-Whisper once on the target machine:

```bash
/home/user/tts-lab/install-whisper.sh
```

Then restart the web UI and use the **STT / Transcribe** tab to transcribe uploaded audio, existing voice profiles, loose references, recent outputs, and extracted Video Intake audio.

Whisper output should be treated as a draft. Review/edit before saving a transcript into a voice profile.

## Changelog order note

The changelog below is ordered newest-to-oldest. Early project versions used labels such as `v0.4`; later versions use labels such as `v0.41`. Treat these as historical release labels, not decimal numbers.


## New in v0.88.2

- Adds **copy Audacity labels** for proposed speech-analysis cuts.
- Adds **copy edit checklist** with cuts ordered from end to beginning so manual deletions do not shift earlier timestamps.
- Keeps the workflow non-destructive: labels/checklists are review aids only.
- Shows queued/running/done status beside the analysis button, useful when Jobs is hidden as its own tab.
- Uses conservative short Audacity labels to avoid importer trouble from long label text.


## New in v0.88.1

- Consolidates heavily overlapping `possible_false_start` proposals so one spoken fumble does not create dozens of duplicate review items.
- Adds raw/suppressed candidate counts to speech analysis summaries.

## New in v0.88

- Adds **Speech Repair Analysis / Diarization foundation** under STT / Transcribe.
- Adds `/api/stt/analysis-status` to report Faster-Whisper, CrisperWhisper, WhisperX, pyannote, and auto-editor readiness.
- Adds `/api/stt/analyze` job queueing for review-first speech analysis.
- Updates the Faster-Whisper helper with optional `--word-timestamps` support for analysis jobs.
- Writes analysis artifacts under `/home/user/tts-lab/output/speech_analysis/`:
  - `*.analysis.json`
  - `*.transcript.md`
  - `*.proposed_cuts.json`
- Produces speaker-aware JSON fields from the beginning: `speaker`, `speaker_label`, and `speaker_segments`.
- Detects filler-word, repeated-word, and possible false-start cut candidates without cutting audio.
- Treats true WhisperX/pyannote diarization and CrisperWhisper verbatim transcription as experimental backend targets rather than pretending they are already validated.

This pass is intentionally non-destructive. Review proposed cuts before future edit/export passes apply them to audio.

## New in v0.87

- Adds an optional **HandAISpoke / AI Studio Bridge** sidecar for short local TTS voice patches.
- Installs `tts_ai_studio_bridge.py`, `run-ai-studio-bridge.sh`, and `.env.ai-studio-bridge.example` under the Web UI folder.
- Adds `/home/user/tts-lab/start-ai-studio-bridge.sh` during install.
- Bridge defaults to `127.0.0.1:7871` and calls the normal Web UI on `127.0.0.1:7870`.
- Bridge requires `X-HandAISpoke-Bridge-Token` from `TTS_AI_STUDIO_BRIDGE_TOKEN`.
- Bridge exposes only status, clone-TTS patch generation, and job-status endpoints; it does not expose the full browser UI.
- Bridge logs request metadata to `/home/user/tts-lab/logs/ui-diagnostics/ai-studio-bridge.log` without logging full base64 audio or long text.
- Corrects architecture wording: local Chatterbox/Qwen3/CosyVoice engines handle cloned/custom voice generation, not Gemini.

Start the bridge only after the main Web UI is running:

```bash
export TTS_AI_STUDIO_BRIDGE_TOKEN='replace-with-a-long-random-token'
/home/user/tts-lab/start-ai-studio-bridge.sh
```

Tunnel only port `7871` if using Cloudflare quick tunnels for AI Studio testing. Do not tunnel the full Web UI port `7870`.

## New in v0.86

- Adds **Maintenance → TTS Lab stack contract** diagnostics for the public-alpha launcher stack.
- Adds `/api/stack-status` to report Web UI version, lab path, launcher status, Conda engine env presence, helper tools, video downloader detection, external-launch status, and log locations.
- Keeps stack setup logic out of the Web UI installer. The Web UI detects and reports stack state; the stack installer remains responsible for Conda/env/model/helper installation and launcher creation.
- Adds copyable stack diagnostics from the Maintenance tab for easier troubleshooting.
- Green-path detection focuses on Chatterbox, Qwen3, and CosyVoice while continuing to label F5 as experimental.

## New in v0.85

- Replaced repeated media handoff button rows with compact **Actions** dropdown menus.
- Preserved existing handoff actions: send to STT, use as Synthesize reference, open in Audio Lab, save as reference, create voice profile, experimental profile creation, extraction, and delete where available.
- Added **Open in Resemble Enhance** to audio Actions menus.
- Added logged external launch actions for local/private desktop workflows:
  - Send to Audacity
  - Open with system default app
  - Open containing folder
- External launch attempts are constrained to known TTS Lab media/output directories and logged to `/home/user/tts-lab/logs/ui-diagnostics/external-actions.log`.

## New in v0.84

- Adds workflow handoff buttons to completed Resemble Enhance jobs: send to STT, use as Synthesize reference, open in Audio Lab, save as loose reference, create voice profile, and delete output.
- Keeps Resemble Enhance isolated from Audio Lab as a processing tab, but allows completed Resemble audio to be reused elsewhere once it exists.
- Improves recovered job-history entries for Resemble Enhance outputs. Older Resemble outputs with sidecar metadata now reappear as Resemble jobs with mode/source context instead of generic `historical-output` entries.
- Improves recovered Audio Lab and Video Intake entries when recognizable sidecar metadata exists, while retaining the generic historical-output fallback for older/unrecognized files.

## New in v0.83

- Fixes a Resemble Enhance upload/selection race where clicking Denoise/Enhance immediately after upload could run against the previously selected file.
- After a Resemble upload succeeds, the UI now refreshes the source list, explicitly selects the newly uploaded file, and only then marks the source ready.
- Disables Resemble Denoise/Enhance buttons while upload/source-refresh is pending.
- Adds a prominent current Resemble source display with detected duration and a long-file VRAM note.
- Resemble job queueing now records the selected source, duration, and device at click time.
- Resemble job logs now include selected source label/duration before staging and warn when Enhance is run on long files.
- Setup/repair buttons now show inline queued-job feedback with an Open Jobs shortcut when Jobs is hidden as a separate tab.

## New in v0.82

- Adds Git LFS detection to the isolated Resemble Enhance status output.
- Adds a Maintenance/Resemble repair action to install `git-lfs` into the dedicated `tts-resemble-enhance` conda environment when conda is available.
- Updates the Resemble Web UI launcher to prepend the isolated environment's `bin` directory to `PATH`, so Resemble subprocesses can find env-local tools such as `git-lfs`.
- Updates the Resemble isolated installer to attempt Git LFS installation during conda-mode setup and to warn clearly in venv mode when Git LFS is missing.
- Improves Resemble runtime failure messages when model download fails because Git LFS is unavailable.
- Keeps Resemble Enhance isolated from Audio Lab and from the main Web UI Python environment.

## New in v0.81

- Updates the isolated Resemble Enhance Web UI runner to avoid `torchaudio.load()` and `torchaudio.save()` for audio-file I/O, because the local Resemble/Torchaudio stack was segfaulting with return code `-11` while loading an 11-second WAV.
- Uses a Python `wave` + NumPy PCM loader/saver in the runner while still using the installed Resemble Enhance package for model inference.
- Normalizes all Resemble inputs, including already-WAV sources, through FFmpeg into a temporary mono 44.1 kHz PCM WAV before running Resemble. This keeps original source files untouched while reducing codec/backend edge cases.
- Improves Resemble job logs to identify the new audio I/O backend and staging behavior.
- Keeps Resemble Enhance isolated from Audio Lab and from the main Web UI Python environment.

## New in v0.80

- Replaces the Resemble compatibility wrapper behavior with a direct Web UI Resemble runner that still keeps the installed package unmodified.
- The direct runner imports Resemble Enhance inference functions and logs every major runtime step: input discovery, audio load, tensor shape, model start/finish, save path, output size, and completion.
- Adds Resemble processing device selection: auto, CUDA/GPU, or CPU.
- Appends subprocess return codes to job logs so silent exits are easier to diagnose.
- Adds work-directory listings after Resemble runs to help locate outputs or prove no output was produced.
- Keeps Resemble Enhance isolated from Audio Lab and from the main Web UI Python environment.

## New in v0.79

- Adds a Web UI compatibility launcher for Resemble Enhance at `/home/user/tts-lab/engines/resemble-enhance/resemble-enhance-webui`.
- The launcher keeps the installed Resemble package unmodified, but monkeypatches `torchaudio.load`/`torchaudio.save` so `pathlib.Path` audio paths are coerced to strings before torchaudio receives them.
- Prefers the compatibility launcher over the direct Resemble CLI in `/api/resemble/status` and Resemble runtime jobs.
- Logs when the compatibility launcher is used, so Path-related Resemble/Torchaudio failures are easier to identify.
- Keeps Resemble Enhance isolated from Audio Lab and from the main Web UI Python environment.

## New in v0.78

- Makes the Resemble Enhance setup/status/install apparatus dismissible from the Resemble tab.
- Adds the dismissed Resemble setup/status item to Maintenance so it can be restored or checked later.
- Adds Maintenance → Resemble Enhance status check/restore shortcuts.
- Fixes Resemble processing for MP3/FLAC/M4A/etc. inputs by staging a temporary WAV copy before invoking the Resemble CLI.
- Logs the staging/conversion step explicitly in the Resemble job log.
- Leaves original Resemble upload/source files unchanged.

## New in v0.77

- Expands the dedicated **Resemble Enhance** tab from setup/status into an isolated runtime test bench.
- Adds Resemble input upload to `/home/user/tts-lab/resemble_uploads/`.
- Adds selectable Resemble input sources from profiles, loose references, recent outputs, Audio Lab outputs, Video Intake extracted audio, and Resemble uploads.
- Adds abortable Resemble Jobs for **Denoise only** and **Enhance speech**.
- Captures full command, stdout/stderr, work directory, raw output directory, and output discovery details in the normal job log.
- Saves final outputs under `/home/user/tts-lab/output/resemble_enhance/`.
- Uses the global filename template system; Resemble jobs supply `[function]` as `denoised` or `enhanced`.
- Completed Resemble jobs appear in Jobs with player, download, handoff buttons, metadata, and logs.
- Keeps Resemble Enhance out of Audio Lab for now.

## New in v0.76

- Adds a dedicated **Resemble Enhance** tab, deliberately separate from Audio Lab for first testing.
- Adds one-button **Install / repair isolated Resemble Enhance environment** workflow.
- Generates `/home/user/tts-lab/install-resemble-enhance.sh` during install.
- Installer prefers a dedicated conda environment named `tts-resemble-enhance` when conda is available, and falls back to `/home/user/tts-lab/engines/resemble-enhance/.venv` when venv mode is used.
- Resemble setup runs as a normal abortable Job with full stdout/stderr logs.
- Adds `/api/resemble/status` detection for installer path, conda availability, venv/conda command candidates, and best detected command.
- Does not add Resemble Enhance into Audio Lab yet; this pass is installation/status only so the engine can be proven locally before deeper integration.

## New in v0.75

- Adds a global filename template field under **Options → File naming defaults**.
- Adds filename tokens including `[source]`, `[function]`, `[custom]`, `[version]`, `[.ext]`, `[YYYYMMDD]`, `[YYYY-MM-DD]`, `[year]`, `[month]`, `[day]`, `[weekday]`, `[time24hour]`, `[time-am-pm]`, and `[timestamp]`.
- Adds **Function file naming** menu options: no function naming, function as prefix, and function as suffix.
- Leaves universal custom filename text blank by default instead of inheriting Audio Lab's old `clean` value on fresh state.
- Shows a live preview of the configured filename template and warns about unknown tokens.
- Audio Lab now passes the function token as `clean`; Video Intake extraction passes it as `extracted`.
- Keeps the simpler dropdown menus as template builders while allowing manual editing of the template.

## New in v0.74

- Moves file naming conventions into **Options → File naming defaults**.
- Universalizes filename text, custom-text placement, date stamp mode, and version suffix mode across Audio Lab and Video Intake extraction.
- Audio Lab and Video Intake now show a compact naming summary instead of duplicating the full naming controls in each workflow panel.
- Migrates older Audio Lab naming preferences into the new global naming defaults when upgrading from older saved state.
- Keeps output format, MP3 bitrate, sample rate, channels, trim, and normalization controls in the workflow panels because those are processing choices, not naming conventions.

## New in v0.73

- Adds flexible panel layout controls under **Options → Panel layout**.
- Adds an operations-panel width slider for the normal left/right layout.
- Adds a **Hide Jobs panel and show Jobs as a tab** option so the active operation can use the full window.
- Adds a **Top/bottom** orientation option for workflows where a horizontal split is easier than left/right.
- Persists layout preferences in `/home/user/tts-lab/config/webui_state.json`.
- Keeps Jobs content and recent audio in one movable panel so job state, logs, and output actions continue to use the same UI IDs.

## New in v0.72

- Moves the **UI diagnostics / click log** out of the main Jobs panel and into **Maintenance / Repairs**.
- Removes the hardware-specific Tagged Script warning from the distributed UI.
- Makes the Profiles “Best path” advisory dismissible and restoreable from Maintenance.
- Makes the Video Intake permitted-use reminder dismissible and restoreable from Maintenance.
- Hides the STT Hugging Face token setup line/panel by default; it now appears only after an HF auth/download warning is seen or when opened from Maintenance.
- Keeps direct Maintenance actions for known fixes, including HF token checks and setup.

## New in v0.71

- Adds a **Maintenance / Repairs** tab for dismissed notices, diagnostics shortcuts, and setup checks.
- Adds a persistent dismissible-notice framework backed by `/home/user/tts-lab/config/webui_state.json`.
- Makes the Audio Lab short-reference advisory dismissible and restoreable from Maintenance.
- Adds Maintenance actions to address known causes directly: prepare Audio Lab for a 12-second short-reference derivative, configure/check Hugging Face token status, open/check Whisper GPU setup, and check the Video URL importer.
- Keeps restoring dismissed notices available for troubleshooting.

## New in v0.70

- Replaces the browser prompt used by **Create voice profile** handoffs with an inline Profiles-tab draft/review panel. The handoff now switches to Profiles, fills the proposed profile name/transcript, shows the source path, and waits for an explicit inline create button.
- Replaces the browser prompt used by **Make experimental profile** with the same inline draft panel plus the generated-audio warning.
- Adds diagnostics events for loading, canceling, and creating pending profile drafts.
- Improves profile-form error handling so missing audio / ZIP import failures appear inline in the Profiles tab instead of browser popups.
- Keeps v0.69 diagnostics panel and v0.68 installer version echo behavior.

## New in v0.69

- Adds a right-side **UI diagnostics / click log** panel. It records browser-side handoff/button clicks, attempted paths, tab switches, POST API successes/failures, and JavaScript errors/unhandled promise rejections.
- Adds **copy diagnostics** and **clear diagnostics** buttons so a failed click can be pasted back into a debugging chat without opening browser developer tools.
- Adds diagnostics to the key handoff flows: **Send to STT**, **Use as Synthesize reference**, **Open in Audio Lab**, **Save as reference**, **Create voice profile**, **Make experimental profile**, and **Extract audio from this source**.
- Keeps v0.68 installer version echo behavior and delegated action-button handling.

## New in v0.68

- Fixes job handoff/action buttons that appeared to do nothing, especially paths containing normal filename characters. The job cards now use delegated `data-action` buttons instead of fragile inline `onclick` JavaScript embedded inside HTML attributes.
- Keeps the v0.67 duplicate-removal behavior: extracted Video Intake audio has a single action row.
- Installer now prints the detected Web UI version when installing and in the final success line.
- Updates the installed README marker to use the detected version instead of the stale older value.

## New in v0.67

- Fixes Video Intake completed-job handoff actions so they visibly switch to the relevant tab and show a clear success/status message.
- Removes duplicate extracted-audio action rows on Video Intake jobs. Extracted audio now has one handoff row near the player/download link instead of one before and one after the player.
- Keeps source-media jobs focused on source actions: **Extract audio from this source** and archived-source download.
- Persists Video Intake and Audio Lab naming/output defaults in `/home/user/tts-lab/config/webui_state.json`, including custom filename text, naming mode, date stamp mode, version suffix mode, output format, sample rate, channels, MP3 bitrate, and normalization.
- Improves profile creation from job-handoff audio by preserving the source audio extension instead of always naming copied source-path audio `audio.wav`.

## New in v0.66

- Fixes a Video Intake UI regression from the archive-first split: the extraction controls now include a clear bottom-of-panel **Extract audio from selected saved source** button after the extraction options.
- Keeps the existing source-picker extraction button and completed-job **Extract audio from this source** button.
- Keeps v0.65 URL-import diagnostics and v0.64 archive-first behavior unchanged.

## New in v0.65

- Improves **Video Intake URL import logging**. Failed URL jobs now write diagnostics to the job log before failing, including URL, work directory, helper directory status, visible helper directory entries, recognized runnable candidates, `yt-dlp` availability, and `TTS_VIDEO_DL_CMD` status.
- Fixes misleading URL helper status. The UI no longer treats `/home/user/video-dl` as ready merely because the folder exists; it now requires a recognized runnable helper, `yt-dlp`, or `TTS_VIDEO_DL_CMD`.
- Adds more recognized `/home/user/video-dl` entrypoint names such as `cli.py`, `downloader.py`, `download_video.py`, and `video_downloader.py`.
- Keeps source archiving and audio extraction as separate actions from v0.64.

## New in v0.64

- Changes **Video Intake** from “download/upload and immediately extract audio” to a two-step archive-first workflow.
- Uploading a video/audio file now saves the source media under `/home/user/tts-lab/output/video_intake/source_media/uploads/` without extracting audio automatically.
- URL import now downloads/saves source media under `/home/user/tts-lab/output/video_intake/source_media/url_imports/` without extracting audio automatically.
- Adds an archived source picker in the Video Intake tab. Select a saved source and then explicitly queue **Extract audio from selected source**.
- Completed Video Intake source jobs include an **Extract audio from this source** button and a source download link.
- Keeps the existing audio extraction options: output format, sample rate, channels, MP3 bitrate, trim, normalization, and filename/date/version naming rules.
- Keeps old v0.62 source directories visible where possible, so previously imported/uploaded source media is not orphaned.

## New in v0.63

- Fixes README/changelog ordering.
- Moves the older v0.52 STT setup guidance out of the bottom of the file and into the setup section above.
- Moves the v0.46 notes back into the v0.46 changelog section.
- Keeps v0.62 behavior unchanged.

## New in v0.62

- Adds a **Video Intake / Extract Audio** tab.
- Supports uploading video/audio files and extracting audio through the existing Jobs system.
- Adds URL import/extraction for lawful/permitted content when `/home/user/video-dl`, `yt-dlp`, or `TTS_VIDEO_DL_CMD` is available.
- Video Intake uses the same practical processing controls as Audio Lab: output format, sample rate, channels, MP3 bitrate, trim, normalization, filename text, date stamp, and version suffix rules.
- Extracted audio is saved under `/home/user/tts-lab/output/video_intake/extracted_audio/` and appears in Jobs / Recent audio.
- Completed extraction jobs include handoff buttons for STT, Synthesize reference, Audio Lab, loose reference saving, and voice profile creation.
- Extracted audio jobs support abort/cancel, logs, browser preview, actual-format download, and best-effort waveform previews.

## New in v0.61

- Audio Lab now supports **Unchanged** for output format, sample rate, and channels, so a single operation does not silently change unrelated properties.
- Adds MP3 bitrate choices: 96k, 128k, 192k, 256k, and 320k.
- Adds Audio Lab naming controls:
  - custom text as prefix, suffix, exact base name, or ignored
  - YYYYMMDD date prefix/suffix
  - version suffix modes including always starting at `-v1`
- Audio Lab still keeps actual-format downloads and before/after waveform previews from v0.60.

## New in v0.60

- Audio Lab now lets you choose output format: WAV, MP3, or FLAC.
- Audio Lab download links now download the actual processed output format, not an MP3 preview mislabeled as WAV.
- Audio Lab jobs now show before/after waveform previews when FFmpeg can decode the source/output audio.
- Abort job feedback is now inline/non-modal instead of using browser confirm/alert popups.

## New in v0.59

- Adds abort/cancel controls for queued/running Jobs, including STT and TTS. Logs are preserved and canceled jobs are marked as canceled instead of error.
- Adds an **Audio Lab** tab for selecting existing audio, trimming it, normalizing with FFmpeg `dynaudnorm`, converting to engine-safe audio, and saving processed copies under `/home/user/tts-lab/output/audio_lab/`.
- Audio Lab outputs appear in Jobs with playback/download and can be used as temporary synthesis references.
- Switching profiles in Synthesize clears stale STT-handoff/upload success notices so the status message matches the current reference source.
- Removes the temporary “GPU setup is separate from Hugging Face token setup” development copy and allows the GPU setup panel to be hidden.
- F5 is now treated as experimental/back-burnered in the engine note after continued local SIGSEGV failures.

## New in v0.57

- Selecting a Synthesize voice profile now fills the editable **Role/name for output** field with the profile name. You can still override it for script roles.
- Hugging Face token setup now shows the dismiss option whenever a token is already configured locally; you do not need to re-test just to dismiss the setup panel.
- **Test GPU transcription support** now queues a logged Jobs entry instead of returning a silent inline result.
- The GPU test uses the selected real STT audio source with the same Faster-Whisper helper command as normal STT, forcing `device=cuda` and `compute=float16`; it should fail honestly if `libcublas.so.12`/cuDNN is missing.

## New in v0.54

- Adds Web UI Hugging Face token setup: save, test, forget, and masked status display.
- Saved HF tokens are stored locally under `/home/user/tts-lab/config/` and passed to STT jobs as `HF_TOKEN`; the token is never printed in the UI or logs.
- Improves STT upload feedback: uploaded files show success, path, duration when available, and are selected automatically.
- Keeps previously uploaded STT audio selectable from the Audio source dropdown.
- Fixes STT source/transcript confusion: selecting an audio source no longer auto-fills the corrected transcript. Saved transcripts are offered with an explicit “Load saved transcript” button and are not sent to Whisper.
- Makes Device=`auto` actually fall back to CPU/int8 if CUDA/cuBLAS/cuDNN fails during transcription.
- GPU fallback is visible as a red warning in the STT job card, with an option to silence future CPU-fallback warnings.
- Replaces successful “save beside selected audio” browser alerts with inline status and preserves the current STT form state.

## New in v0.53

- Moves STT / Faster-Whisper transcription into the main **Jobs** system.
- Transcription now creates a visible STT job with status, job log, transcript preview, copy/load/save actions, and metadata.
- Removes browser-alert traceback behavior from normal transcription failures. Errors belong in the job log.
- Fixes CPU transcription defaults: CPU uses `int8` by default instead of invalid `float16`.
- Adds an advanced Compute type selector for STT when needed.
- Adds Hugging Face token setup guidance in the STT tab.
- Installs helper scripts:
  - `/home/user/tts-lab/login-hf-token.sh`
  - `/home/user/tts-lab/install-whisper-cuda-libs.sh`
- The browser can now preserve the active tab via URL hash, e.g. `/#stt`.
- The “Faster-Whisper ready” notice can be dismissed in the browser.
- STT transcript boxes are cleared/reloaded by selected audio path, avoiding stale Synthesize text leaking into transcription.

## New in v0.52

- Adds the first **STT / Transcribe** tab powered by Faster-Whisper.
- Adds upload/select audio for transcription from profiles, loose references, recent outputs, and STT uploads.
- Adds draft transcript review/edit/copy/save flow.
- Adds optional `/home/user/tts-lab/install-whisper.sh` setup for the separate `tts-whisper` environment.

## New in v0.50

- Cleans up the **Options** tab so it no longer has both a dropdown and duplicate preset buttons.
- Keeps preset buttons only:
  - **Show everything**
  - **Producer default**
  - **Hide the science fair**
  - **Minimal**
- Makes presets meaningfully different:
  - Show everything exposes every lever.
  - Producer default keeps practical production controls but hides generated-output experimental profile creation.
  - Hide the science fair keeps the profile/synthesis workflow clean and hides debugging/metadata clutter.
  - Minimal hides nearly everything except basic play/download/use-as-reference controls.
- Adds a visible **Current preset** label and marks individual checkbox changes as **Custom**.
- Keeps the individual checkboxes for fine tuning after choosing a preset.

## New in v0.49

- Adds an **Upload audio** button beside the Synthesize tab's Reference audio path field.
- Uploaded Synthesize-tab reference audio is copied into `/home/user/tts-lab/references/` and the path field is filled automatically.
- Adds an **Options** tab for UI clutter control.
- Options are persisted with the remembered form state in:

```text
/home/user/tts-lab/config/webui_state.json
```

- Adds interface modes: Beginner, Producer, Advanced, and Minimal.
- Adds toggles for showing/hiding:
  - advanced engine options
  - profile import/export/save tools
  - generated-output experimental profile tools
  - text/metadata/copy helpers
  - job logs
  - delete buttons
- Hiding controls does not delete files, profiles, logs, metadata, or remembered form data.

## New in v0.48

- Adds a **Remember this Synthesize form** checkbox, checked by default.
- Persists the current Synthesize fields across refreshes/restarts/upgrades:
  - engine
  - voice profile
  - role/name
  - reference audio path
  - reference transcript
  - text to synthesize
  - Qwen3 x-vector-only
  - Chatterbox split/concat option
- Stores remembered form state outside the replaceable web UI folder at:

```text
/home/user/tts-lab/config/webui_state.json
```

- Adds **clear remembered form** without deleting audio, profiles, or the currently visible fields.
- Restores/expands **view text / metadata** for produced audio, separate from logs.
- Adds copy buttons for synthesized text, reference transcript, and reference audio path.
- Adds **Copy reference text** and **Copy reference path** buttons to the main Synthesize form.
- Splits page scrolling into independent left/right panels, with Generate buttons kept sticky at the bottom of the working panel.

## New in v0.47

- Fixes a JavaScript syntax error introduced in v0.46 by a multiline prompt string.
- The broken script prevented the startup API calls from populating the Engine dropdown, Voice profile dropdown, default reference path, and Recent audio list.
- Keeps the v0.46 interface changes: safe left-side profile creation from original reference audio, and generated-output promotion clearly marked experimental.

## New in v0.46

- Adds **Save current reference as voice profile** to the Synthesize tab for the safe/original-audio path.
- Adds **use as reference**, **promote to profile**, and **delete** controls directly to completed Jobs entries, not just the Recent audio / Loose files area.
- Adds best-effort audio duration display for profiles, loose references, recent outputs, and completed jobs.
- Flags reference clips under 10 seconds as short, since that can contribute to Chatterbox/ElevenLabs-style reference warnings or rejection.
- Renames generated-output promotion controls to **make experimental profile** to distinguish them from normal human-reference profiles.
- Clarifies that **Use as temporary reference** only fills the current synthesis form and does not save a reusable profile.
- Keeps generated-output promotion explicit to avoid clone-of-clone artifact buildup.

## New in v0.44

- Fixes MP3 preview generation. v0.43 used temporary files ending in `.mp3.tmp`, which can make ffmpeg fail to infer the MP3 output format. v0.44 writes `.tmp.mp3` and explicitly sets `-f mp3`.
- Fixes the player-cutoff-after-generation behavior by stopping the auto-poll loop when jobs finish. Previous polling could re-render the Recent audio list after generation, destroying active `<audio>` elements mid-play.
- Recent audio now avoids re-rendering while audio is actively playing unless the user performs an explicit destructive action such as delete.
- FFmpeg preview errors are captured into the job log instead of only saying preview generation failed.
- Retains the v0.43.1 log-viewer fix and v0.43 MP3-preview approach.

## New in v0.42

### Stable log viewer

The Jobs section no longer embeds log textareas inside the auto-refreshing job list. Logs now open in a stable viewer panel with:

- refresh log
- copy log
- bottom
- close log

This avoids the previous “anti-scrolling” behavior where refreshes could collapse or fight the log scroll position.

### Persistent job history

New jobs now persist their job metadata and log text under:

```text
/home/user/tts-lab/output/job_history/
```

This means completed-job logs survive page refreshes and web UI restarts.

Outputs created before v0.42 did not have persistent job logs. v0.44 recovers those old output WAVs into the Jobs list as `historical-output` entries, but their log viewer will honestly say that no saved subprocess log exists. Future jobs will keep logs.

## New in v0.41

- Recent audio entries have a **delete** button.
- Delete removes the generated audio file, its `.wav.json` metadata sidecar, and hidden chunk-part folders when present.
- Delete is restricted to `/home/user/tts-lab/output`.

## New in v0.4

- Generated WAV files are rewritten through `ffmpeg` as browser-safe PCM16 WAVs with fresh RIFF headers.
- Audio routes support HTTP byte-range requests for reliable browser playback/seeking.
- Audio URLs include cache-busting file size/mtime keys.
- Running jobs do not show a player until the output file exists and the job is no longer running.
- Recent audio hides internal chunk-part WAVs from split Chatterbox renders.

## New in v0.3

- Qwen3 x-vector-only mode no longer sends reference transcript text at the same time.
- Chatterbox can split multi-sentence text into short renders and concatenate the WAVs.
- Tagged-script tab warns that batch work is heavy on a 6GB laptop GPU and adds cooldowns between lines.
- Exit-code 137 / killed jobs are reported as likely RAM/VRAM pressure.

## New in v0.2

### Voice profiles

A voice profile is a first-class object:

```text
/home/user/tts-lab/references/profiles/chris-dry-executive/
  audio.wav
  transcript.txt
  voice-profile.json
```

The Synthesize tab can use a profile directly, so you do not need to manually paste reference paths and transcripts every time.

### Inline playback

Recent outputs, loose references, and profiles use inline `<audio controls>` playback.

### Selectable samples

Recent output samples can be loaded as the current reference with **Use as reference**. If the output has sidecar metadata, its synthesized text is loaded as the reference transcript.

Generated samples are **not** automatically converted into profile references. Use **Promote to profile** only when you knowingly accept clone-of-clone artifact risk.

### Transcript pairing

Generated outputs get a sidecar metadata file:

```text
example.wav
example.wav.json
```

The sidecar remembers the engine, text, reference audio, and reference transcript used to create the file.

Loose reference uploads can also save a matching `.txt` transcript beside the audio.

### Portable profile ZIPs

Profiles can be exported as ZIPs containing:

```text
voice-profile.json
audio.wav
transcript.txt
```

The Profiles tab can also import a ZIP profile package and add it to the library.

## Existing features retained

- Single-line generation with engine selector.
- Tagged-script rendering for lines like `EXEC: ...`, `TUCKER: ...`, `ANALYST: ...`.
- Role map JSON supports profile slugs, e.g. `{ "EXEC": {"engine": "chatterbox", "profile": "chris-dry-executive"} }`.
- Reference audio path and transcript fields remain available for manual testing.
- Qwen3 x-vector-only checkbox.
- One-at-a-time job queue to avoid 6GB VRAM pileups.
- WAV playback, downloads, output listing, and profile ZIP import/export.
- No third-party Python web framework required.

## Safety / exposure

By default it binds only to `127.0.0.1`, meaning only the local machine can access it. Do **not** expose this directly to the public internet. It can execute local synth jobs and read/write files inside the TTS lab directories.
