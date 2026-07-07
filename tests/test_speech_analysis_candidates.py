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


if __name__ == "__main__":
    test_filler_and_repeat_candidates()
    print("ok")
