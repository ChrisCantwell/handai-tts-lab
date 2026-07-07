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

    def add_seq(seq: str, start: float, conf: float = 0.9, low_words: set[str] | None = None):
        low_words = low_words or set()
        t = start
        for raw in seq.split():
            prob = 0.12 if raw.lower().strip(".,!?'") in low_words else conf
            words.append({"word": raw, "start": round(t, 2), "end": round(t + 0.18, 2), "probability": prob})
            t += 0.32
        return t

    add_seq("chat GPT is taken on a diversity of roles in this one you are the curious interviewer", 15.13)
    add_seq("chat GPT is taken on a number of", 25.09)
    add_seq("fucking Christ", 28.27, conf=0.3)
    add_seq("chat GPT is taken on a diversity of roles current", 30.11)
    add_seq("chat GPT is taken on a diversity of roles in this one you are the curious interviewer", 34.85)

    add_seq("the disruptive collaborator partner this the disruptive collaborative partner element is not usually an on air", 53.53, low_words={"the", "this"})
    add_seq("disruptive collaborative partner element is not usually an on air character", 63.39)

    add_seq("it just so happens that we're having a really good time in learning a lot in the process", 91.21)
    add_seq("that story was worth telling and that's why we're telling", 94.89)
    add_seq("that story was worth telling and that's why we're telling it", 100.76)

    data = {"text": " ".join(w["word"] for w in words), "segments": [{"start": 0.0, "end": 105.0, "text": " ".join(w["word"] for w in words), "words": words}]}
    result = app.build_speech_analysis_result(Path("example.wav"), data, {"analysis_engine": "faster-whisper-analysis", "diarization_mode": "speaker-schema"})
    false_starts = [c for c in result["proposed_cuts"] if c["type"] == "possible_false_start"]
    assert result["summary"]["raw_false_start_count"] > len(false_starts)
    assert result["summary"]["suppressed_duplicate_cut_count"] > 0
    assert len(false_starts) == 3
    assert any(c.get("consolidated") for c in false_starts)
    spans = [(round(c["start"], 2), round(c["end"], 2)) for c in false_starts]
    assert spans == [(15.13, 34.85), (53.53, 63.39), (94.89, 100.76)]


if __name__ == "__main__":
    test_filler_and_repeat_candidates()
    test_false_start_candidates_are_consolidated()
    print("ok")
