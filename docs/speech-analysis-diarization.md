# Speech Repair Analysis and Diarization Foundation

Web UI v0.88 adds the first local foundation for spoken-word repair analysis. The goal is to turn long, messy speech audio into structured data that can later drive reviewable audio edits.

This is not a destructive editor yet. It creates analysis artifacts and proposed edit decisions.

## Why this exists

Ordinary transcripts are not enough for podcast archives or live-radio material. A useful archive needs to track:

```text
who spoke
when they spoke
what they said
whether the speaker is host / caller / clip / guest / unknown
which sections are filler, stutter, restart, or possible false start
what cuts were proposed, accepted, rejected, or exported
```

## v0.88 behavior

The first implementation uses the existing Faster-Whisper helper as the working baseline. Analysis jobs request word timestamps when supported, then generate:

- `analysis.json` with transcript text, words, speaker-aware segments, proposed cuts, and backend metadata
- `transcript.md` with speaker/timestamp headings
- `proposed_cuts.json` containing reviewable edit candidates

Files are written under:

```text
/home/user/tts-lab/output/speech_analysis/
```

## Proposed cuts

The first candidate detector is intentionally conservative. It can flag:

- filler words such as `um`, `uh`, `ah`, `er`, `erm`
- adjacent repeated words that may be stutters
- nearby repeated phrase starts that may be false starts

Only obvious filler candidates with real word timestamps are marked as potentially safe auto-cuts. False-start candidates are review-only.

## Diarization

Diarization means estimating **who spoke when**. It usually produces anonymous labels such as:

```text
SPEAKER_00
SPEAKER_01
SPEAKER_02
```

It does not automatically know which speaker is the host, a caller, a cohost, or a news clip. v0.88 stores both machine speaker IDs and editable human labels:

```json
{
  "speaker": "SPEAKER_00",
  "speaker_label": "unknown"
}
```

Future passes should allow labels such as:

```text
unknown
host
caller
guest
cohost
news_clip
music
silence
```

## Backend targets

The STT tab reports readiness for these backend targets:

- Faster-Whisper baseline analysis
- CrisperWhisper verbatim transcription target
- WhisperX alignment / diarization target
- pyannote.audio diarization target
- auto-editor dead-air editing tool

CrisperWhisper, WhisperX, and pyannote are not claimed as validated merely because v0.88 knows about them. They require separate install and validation passes.

## Future passes

Likely next work:

1. Install/validate a CrisperWhisper runtime for verbatim filler/stutter transcription.
2. Install/validate WhisperX + pyannote diarization.
3. Add a speaker-label review UI.
4. Export Audacity label tracks.
5. Add preview/accept/reject controls for proposed cuts.
6. Apply accepted cuts with ffmpeg using short crossfades.
7. Preserve full change logs for source, model, speaker labels, proposed cuts, accepted cuts, rejected cuts, output files, and timing stats.

## Principle

The system can be magical, but not mysterious. Every future edit should be traceable from source audio to transcript, model/backend, speaker labels, proposed cuts, accepted cuts, exported audio, and logs.
