#!/usr/bin/env python3
"""Small faster-whisper helper used by TTS Lab Unified Web UI."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def compatible_compute_type(device: str, requested: str) -> str:
    requested = (requested or "auto").strip().lower()
    if requested and requested != "auto":
        return requested
    if device == "cpu":
        # float16 is a GPU-oriented default. Faster-Whisper rejects it on many CPU backends.
        return "int8"
    if device == "cuda":
        return "float16"
    return "auto"


def looks_like_cuda_runtime_error(exc: BaseException) -> bool:
    text = str(exc)
    needles = (
        "libcublas.so.12",
        "libcudnn",
        "CUDA failed",
        "CUDA error",
        "cublas",
        "cudnn",
        "CUDA driver",
    )
    return any(n.lower() in text.lower() for n in needles)


def load_model(model_size: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel
    requested_compute = (compute_type or "auto").strip().lower()
    used_compute = compatible_compute_type(device, requested_compute)
    return WhisperModel(model_size, device=device, compute_type=used_compute), device, used_compute


def transcribe_once(model_size: str, audio: Path, language: str, device: str, compute_type: str):
    model, used_device, used_compute = load_model(model_size, device, compute_type)
    kwargs = {"beam_size": 5, "vad_filter": True}
    if language.strip() and language.strip().lower() != "auto":
        kwargs["language"] = language.strip()
    segments, info = model.transcribe(str(audio), **kwargs)
    items = []
    text_parts = []
    for seg in segments:
        d = {"start": float(seg.start), "end": float(seg.end), "text": seg.text.strip()}
        items.append(d)
        text_parts.append(d["text"])
    return {
        "text": " ".join([part for part in text_parts if part]).strip(),
        "segments": items,
        "language": getattr(info, "language", ""),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "duration": float(getattr(info, "duration", 0.0) or 0.0),
        "model": model_size,
        "device": used_device,
        "compute_type": used_compute,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--model", default="base")
    ap.add_argument("--language", default="")
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    ap.add_argument("--compute-type", default="auto")
    args = ap.parse_args()

    audio = Path(args.audio)
    if not audio.exists():
        raise SystemExit(f"Audio file not found: {audio}")

    fallback_warning = ""
    if args.device == "auto":
        try:
            result = transcribe_once(args.model, audio, args.language, "cuda", compatible_compute_type("cuda", args.compute_type))
        except Exception as exc:
            if not looks_like_cuda_runtime_error(exc):
                raise
            fallback_warning = (
                "GPU/CUDA transcription failed, so Device=auto fell back to CPU/int8. "
                "Install CUDA runtime libraries for Faster-Whisper if you want GPU transcription. "
                f"CUDA error: {exc}"
            )
            print(fallback_warning, file=sys.stderr)
            result = transcribe_once(args.model, audio, args.language, "cpu", "int8")
        result["requested_device"] = "auto"
    else:
        result = transcribe_once(args.model, audio, args.language, args.device, args.compute_type)
        result["requested_device"] = args.device

    result["requested_compute_type"] = args.compute_type
    if fallback_warning:
        result["fallback_warning"] = fallback_warning
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
