#!/usr/bin/env python3
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "webui" / "tts_webui.py"
spec = importlib.util.spec_from_file_location("tts_webui_for_analysis_test", MOD)
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
assert spec.loader is not None
spec.loader.exec_module(app)


def test_filler_and_repeat_candidates():
    data = {
        "text": "um I I want to start again I want to start again",
        "segments": [
            {
                "start": 0.0,
                "end": 4.5,
                "text": "um I I want to start again I want to start again",
                "words": [
                    {"word": "um", "start": 0.1, "end": 0.3, "probability": 0.9},
                    {"word": "I", "start": 0.4, "end": 0.5, "probability": 0.9},
                    {"word": "I", "start": 0.55, "end": 0.65, "probability": 0.9},
                    {"word": "want", "start": 0.7, "end": 0.9, "probability": 0.9},
                    {"word": "to", "start": 0.95, "end": 1.05, "probability": 0.9},
                    {"word": "start", "start": 1.1, "end": 1.3, "probability": 0.9},
                    {"word": "again", "start": 1.35, "end": 1.6, "probability": 0.9},
                    {"word": "I", "start": 2.0, "end": 2.1, "probability": 0.9},
                    {"word": "want", "start": 2.15, "end": 2.35, "probability": 0.9},
                    {"word": "to", "start": 2.4, "end": 2.5, "probability": 0.9},
                    {"word": "start", "start": 2.55, "end": 2.75, "probability": 0.9},
                    {"word": "again", "start": 2.8, "end": 3.0, "probability": 0.9},
                ],
            }
        ],
    }
    result = app.build_speech_analysis_result(Path("example.wav"), data, {"analysis_engine": "faster-whisper-analysis", "diarization_mode": "speaker-schema"})
    types = {c["type"] for c in result["proposed_cuts"]}
    assert "filler" in types
    assert "stutter_or_repeated_word" in types
    assert result["summary"]["word_count"] == 12
    assert result["speaker_segments"][0]["speaker"] == "SPEAKER_00"


def test_false_start_candidates_are_consolidated():
    words = []
    text_words = (
        "chat GPT is taken on a diversity of roles in this one you are the curious interviewer "
        "other times you have been an institutional caution voice or I might say chat GPT is taken "
        "on a number of fucking Christ chat GPT is taken on a diversity of roles in this one you are "
        "the curious interviewer"
    ).split()
    t = 0.0
    for word in text_words:
        words.append({"word": word, "start": t, "end": t + 0.18, "probability": 0.9})
        t += 0.32
    data = {"text": " ".join(text_words), "segments": [{"start": 0.0, "end": t, "text": " ".join(text_words), "words": words}]}
    raw_cuts = []
    norm = [app._norm_word(app._word_text(w)) for w in app._words_from_transcript_result(data)]
    seen = {}
    expanded_words = app._words_from_transcript_result(data)
    for i in range(0, max(0, len(norm) - 2)):
        phrase = tuple(norm[i:i+3])
        if any(not x for x in phrase):
            continue
        if phrase in seen:
            prev = seen[phrase]
            gap = float(expanded_words[i].get("start") or 0.0) - float(expanded_words[prev+2].get("end") or 0.0)
            if 0 <= gap <= 20:
                raw_cuts.append({"type": "possible_false_start", "start": expanded_words[prev]["start"], "end": expanded_words[i]["start"], "speaker": "SPEAKER_00"})
        else:
            seen[phrase] = i
    result = app.build_speech_analysis_result(Path("example.wav"), data, {"analysis_engine": "faster-whisper-analysis", "diarization_mode": "speaker-schema"})
    false_starts = [c for c in result["proposed_cuts"] if c["type"] == "possible_false_start"]
    assert len(raw_cuts) > 8
    assert len(false_starts) < len(raw_cuts)
    assert result["summary"]["suppressed_duplicate_cut_count"] > 0
    assert any(c.get("consolidated") for c in false_starts)


if __name__ == "__main__":
    test_filler_and_repeat_candidates()
    test_false_start_candidates_are_consolidated()
    print("ok")
