#!/usr/bin/env python3
"""Local smoke-test client for the HandAISpoke / AI Studio TTS bridge."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the HandAISpoke TTS bridge")
    parser.add_argument("--url", default="http://127.0.0.1:7871/api/ai-studio-bridge/clone-tts")
    parser.add_argument("--token", required=True)
    parser.add_argument("--ref", required=True, help="Path to a short WAV/MP3 reference audio file")
    parser.add_argument("--text", default="This is a local HandAISpoke voice patch test.")
    parser.add_argument("--engine", default="chatterbox", choices=["chatterbox", "qwen3", "cosyvoice"])
    parser.add_argument("--save", default="bridge-test-output.wav")
    args = parser.parse_args()

    ref_path = Path(args.ref).expanduser().resolve()
    if not ref_path.exists():
        raise SystemExit(f"Reference audio not found: {ref_path}")

    payload = {
        "request_id": "local-smoke-test",
        "engine": args.engine,
        "text": args.text,
        "reference_audio_base64": base64.b64encode(ref_path.read_bytes()).decode("ascii"),
        "reference_mime_type": "audio/wav" if ref_path.suffix.lower() == ".wav" else "audio/mpeg",
        "return_format": "json_base64",
        "mode": "sync",
        "timeout_seconds": 90,
    }

    req = Request(
        args.url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-HandAISpoke-Bridge-Token": args.token,
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        raise

    print(json.dumps({k: v for k, v in data.items() if k != "audio_base64"}, indent=2))
    if not data.get("ok"):
        return 1

    audio = base64.b64decode(data["audio_base64"])
    out = Path(args.save).expanduser().resolve()
    out.write_bytes(audio)
    print(f"Saved {len(audio)} bytes to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
