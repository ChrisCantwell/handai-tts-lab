#!/usr/bin/env python3
"""
HandAISpoke / Google AI Studio bridge for TTS Unified WebUI.

Runs as a small authenticated sidecar on localhost:7871 and forwards short
voice-patch requests to the existing TTS Unified WebUI on localhost:7870.

Security model:
- Tunnel this bridge only, not the full TTS WebUI.
- Requires X-HandAISpoke-Bridge-Token.
- Synthesizes audio only.
- Does not expose browse/delete/restart/desktop-launch/profile/full UI controls.
- Does not claim Gemini performs voice cloning; local configured TTS engines do.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


VERSION = "0.87"

LAB = Path(os.environ.get("TTS_LAB", "/home/user/tts-lab"))
OUT_DIR = Path(os.environ.get("TTS_OUT", str(LAB / "output")))
REF_DIR = Path(os.environ.get("TTS_REF", str(LAB / "references")))
BRIDGE_REF_DIR = Path(os.environ.get("TTS_AI_STUDIO_BRIDGE_REF_DIR", str(REF_DIR / "ai_studio_bridge")))
BRIDGE_OUT_DIR = Path(os.environ.get("TTS_AI_STUDIO_BRIDGE_OUT_DIR", str(OUT_DIR / "ai_studio_bridge")))
LOG_DIR = Path(os.environ.get("TTS_UI_DIAGNOSTICS_DIR", str(LAB / "logs" / "ui-diagnostics")))
BRIDGE_LOG = LOG_DIR / "ai-studio-bridge.log"

WEBUI_BASE = os.environ.get("TTS_WEBUI_BASE", "http://127.0.0.1:7870").rstrip("/")
HOST = os.environ.get("TTS_AI_STUDIO_BRIDGE_HOST", "127.0.0.1")
PORT = int(os.environ.get("TTS_AI_STUDIO_BRIDGE_PORT", "7871"))
TOKEN = os.environ.get("TTS_AI_STUDIO_BRIDGE_TOKEN", "")

ALLOWED_ORIGINS = [
    x.strip()
    for x in os.environ.get("TTS_AI_STUDIO_BRIDGE_ALLOWED_ORIGINS", "*").split(",")
    if x.strip()
]

ALLOWED_ENGINES = {
    x.strip().lower()
    for x in os.environ.get("TTS_AI_STUDIO_BRIDGE_ALLOWED_ENGINES", "chatterbox,qwen3,cosyvoice").split(",")
    if x.strip()
}

MAX_TEXT_CHARS = int(os.environ.get("TTS_AI_STUDIO_BRIDGE_MAX_TEXT_CHARS", "1200"))
MAX_REF_BYTES = int(os.environ.get("TTS_AI_STUDIO_BRIDGE_MAX_REF_BYTES", str(20 * 1024 * 1024)))
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("TTS_AI_STUDIO_BRIDGE_TIMEOUT_SECONDS", "90"))
POLL_INTERVAL_SECONDS = float(os.environ.get("TTS_AI_STUDIO_BRIDGE_POLL_INTERVAL_SECONDS", "0.5"))

SAFE_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")
VALID_RETURN_FORMATS = {"json", "json_base64", "base64", "raw", "raw_wav", "wav"}
VALID_MODES = {"sync", "async"}


def ensure_dirs() -> None:
    BRIDGE_REF_DIR.mkdir(parents=True, exist_ok=True)
    BRIDGE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def safe_slug(value: str, fallback: str = "request") -> str:
    value = SAFE_SLUG.sub("_", value.strip())[:96].strip("._-")
    return value or fallback


def log_event(level: str, stage: str, message: str, **data) -> None:
    ensure_dirs()
    row = {
        "ts": iso_now(),
        "level": level,
        "stage": stage,
        "message": message,
        **data,
    }
    with BRIDGE_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def decode_b64(value: str) -> bytes:
    value = (value or "").strip()
    if "," in value and value.lower().startswith("data:"):
        value = value.split(",", 1)[1]
    return base64.b64decode(value, validate=False)


def ext_from_mime(mime: str) -> str:
    mime = (mime or "").split(";", 1)[0].strip().lower()
    if mime in {"audio/wav", "audio/x-wav", "audio/wave"}:
        return ".wav"
    if mime in {"audio/mpeg", "audio/mp3"}:
        return ".mp3"
    if mime == "audio/flac":
        return ".flac"
    guessed = mimetypes.guess_extension(mime or "")
    return guessed if guessed in {".wav", ".mp3", ".flac", ".m4a", ".ogg"} else ".wav"


def webui_request(method: str, path: str, payload: dict | None = None, timeout: float = 20) -> dict:
    url = WEBUI_BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TTS WebUI HTTP {exc.code}: {raw[:1000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach TTS WebUI at {WEBUI_BASE}: {exc}") from exc


def wait_for_job(job_id: str, timeout_seconds: float) -> dict:
    deadline = time.time() + timeout_seconds
    last: dict = {}
    while time.time() < deadline:
        last = webui_request("GET", f"/api/jobs/{job_id}", timeout=10)
        job = last.get("job") or {}
        if job.get("status") in {"done", "error", "canceled"}:
            return job
        time.sleep(POLL_INTERVAL_SECONDS)
    job = (last.get("job") or {}) if isinstance(last, dict) else {}
    job["status"] = job.get("status") or "timeout"
    return job


def minimal_job_payload(job: dict) -> dict:
    """Return the job facts useful to a remote helper without large logs/commands."""
    keep = {
        "id",
        "kind",
        "status",
        "engine",
        "role",
        "output_path",
        "duration_seconds",
        "error",
        "warning",
        "returncode",
        "created_at",
        "started_at",
        "finished_at",
    }
    return {k: job.get(k) for k in keep if k in job and job.get(k) is not None}


class Handler(BaseHTTPRequestHandler):
    server_version = f"HandAISpokeTTSBridge/{VERSION}"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")

    def origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        return "*" in ALLOWED_ORIGINS or not origin or origin in ALLOWED_ORIGINS

    def cors_origin(self) -> str:
        origin = self.headers.get("Origin", "")
        if "*" in ALLOWED_ORIGINS:
            return origin or "*"
        if origin and origin in ALLOWED_ORIGINS:
            return origin
        return ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS else "*"

    def send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-HandAISpoke-Bridge-Token")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")

    def send_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def send_audio(self, path: Path, content_type: str = "audio/wav") -> None:
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def require_auth(self) -> bool:
        if not TOKEN:
            self.send_json(
                {
                    "ok": False,
                    "error": "Bridge token is not configured. Set TTS_AI_STUDIO_BRIDGE_TOKEN before exposing the bridge.",
                },
                503,
            )
            return False
        if not self.origin_allowed():
            log_event("warn", "origin", "Rejected bridge request from disallowed origin", origin=self.headers.get("Origin", ""), path=self.path)
            self.send_json({"ok": False, "error": "Origin not allowed"}, 403)
            return False
        supplied = self.headers.get("X-HandAISpoke-Bridge-Token", "")
        if supplied != TOKEN:
            log_event("warn", "auth", "Rejected bridge request with missing or invalid token", origin=self.headers.get("Origin", ""), path=self.path)
            self.send_json({"ok": False, "error": "Unauthorized"}, 401)
            return False
        return True

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/ai-studio-bridge/status":
            if not self.require_auth():
                return
            try:
                meta = webui_request("GET", "/api/meta", timeout=5)
                self.send_json(
                    {
                        "ok": True,
                        "bridge": "handaispoke-tts-ai-studio-bridge",
                        "bridge_version": VERSION,
                        "webui_base": WEBUI_BASE,
                        "webui_version": meta.get("version"),
                        "allowed_engines": sorted(ALLOWED_ENGINES),
                        "max_text_chars": MAX_TEXT_CHARS,
                        "max_reference_bytes": MAX_REF_BYTES,
                        "log_path": str(BRIDGE_LOG),
                        "message": "Local TTS bridge active: cloned/custom voice generation is handled by your configured local TTS engine, not Gemini.",
                    }
                )
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc), "webui_base": WEBUI_BASE}, 502)
            return

        if path.startswith("/api/ai-studio-bridge/jobs/"):
            if not self.require_auth():
                return
            job_id = safe_slug(path.rsplit("/", 1)[-1])
            try:
                data = webui_request("GET", f"/api/jobs/{job_id}", timeout=10)
                if "job" in data:
                    data = {"job": minimal_job_payload(data.get("job") or {})}
                self.send_json(data)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, 502)
            return

        self.send_json({"ok": False, "error": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path != "/api/ai-studio-bridge/clone-tts":
            self.send_json({"ok": False, "error": "Not found"}, 404)
            return

        if not self.require_auth():
            return

        request_id = ""
        started = time.time()
        try:
            ensure_dirs()
            body = self.read_json_body()

            request_id = safe_slug(str(body.get("request_id") or uuid.uuid4().hex))
            text = str(body.get("text") or "").strip()
            if not text:
                raise ValueError("text is required")
            if len(text) > MAX_TEXT_CHARS:
                raise ValueError(f"text is too long for bridge patch mode: {len(text)} chars > {MAX_TEXT_CHARS}")

            engine = str(body.get("engine") or "chatterbox").strip().lower()
            if engine not in ALLOWED_ENGINES:
                raise ValueError(f"engine is not allowed for bridge mode: {engine}")

            ref_b64 = str(body.get("reference_audio_base64") or body.get("referenceAudio") or "").strip()
            if not ref_b64:
                raise ValueError("reference_audio_base64 is required")

            ref_mime = str(body.get("reference_mime_type") or body.get("mimeType") or "audio/wav").strip()
            ref_bytes = decode_b64(ref_b64)
            if not ref_bytes:
                raise ValueError("reference audio decoded to zero bytes")
            if len(ref_bytes) > MAX_REF_BYTES:
                raise ValueError(f"reference audio is too large: {len(ref_bytes)} bytes > {MAX_REF_BYTES}")

            ref_hash = hashlib.sha256(ref_bytes).hexdigest()
            ref_path = BRIDGE_REF_DIR / f"{request_id}_{ref_hash[:12]}{ext_from_mime(ref_mime)}"
            ref_path.write_bytes(ref_bytes)

            out_path = BRIDGE_OUT_DIR / f"{request_id}_{engine}.wav"
            ref_text = str(body.get("reference_text") or body.get("ref_text") or "").strip()
            x_vector_only = bool(body.get("x_vector_only", engine == "qwen3"))
            timeout_seconds = float(body.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
            timeout_seconds = max(1.0, min(timeout_seconds, DEFAULT_TIMEOUT_SECONDS))
            return_format = str(body.get("return_format") or "json_base64").strip().lower()
            mode = str(body.get("mode") or "sync").strip().lower()
            if return_format not in VALID_RETURN_FORMATS:
                raise ValueError(f"return_format is not supported: {return_format}")
            if mode not in VALID_MODES:
                raise ValueError(f"mode is not supported: {mode}")

            payload = {
                "engine": engine,
                "role": "ai_studio_patch",
                "text": text,
                "ref": str(ref_path),
                "ref_text": ref_text,
                "x_vector_only": x_vector_only,
                "output": str(out_path),
                "split_on_sentences": False,
                "source": "handaispoke-ai-studio-bridge",
                "bridge_request_id": request_id,
            }

            log_event(
                "info",
                "request",
                "Queueing local TTS patch",
                request_id=request_id,
                origin=self.headers.get("Origin", ""),
                engine=engine,
                text_chars=len(text),
                reference_bytes=len(ref_bytes),
                reference_sha256=ref_hash[:16],
                reference_mime=ref_mime,
                mode=mode,
                return_format=return_format,
            )

            queued = webui_request("POST", "/api/generate", payload, timeout=20)
            job = queued.get("job") or {}
            job_id = job.get("id")
            if not job_id:
                raise RuntimeError(f"TTS WebUI did not return a job id: {queued}")

            log_event("info", "queued", "TTS WebUI job queued", request_id=request_id, job_id=job_id)

            if mode == "async":
                self.send_json({"ok": True, "request_id": request_id, "job_id": job_id, "job": minimal_job_payload(job)}, 202)
                return

            final_job = wait_for_job(job_id, timeout_seconds)
            status = final_job.get("status")
            if status != "done":
                log_event(
                    "warn",
                    "incomplete",
                    "TTS job did not complete during sync wait",
                    request_id=request_id,
                    job_id=job_id,
                    status=status,
                    error=final_job.get("error"),
                    elapsed_seconds=round(time.time() - started, 3),
                )
                self.send_json(
                    {
                        "ok": False,
                        "request_id": request_id,
                        "job_id": job_id,
                        "status": status,
                        "error": final_job.get("error") or "job did not complete before timeout",
                        "job": minimal_job_payload(final_job),
                    },
                    202 if status not in {"error", "canceled"} else 500,
                )
                return

            output_path = Path(str(final_job.get("output_path") or final_job.get("output") or out_path))
            if not output_path.exists() or output_path.stat().st_size <= 0:
                raise RuntimeError(f"Completed job output missing or empty: {output_path}")

            duration = final_job.get("duration_seconds")
            audio_bytes = output_path.read_bytes()
            elapsed = round(time.time() - started, 3)
            log_event(
                "success",
                "complete",
                "Local TTS patch complete",
                request_id=request_id,
                job_id=job_id,
                status=status,
                output_path=str(output_path),
                output_bytes=len(audio_bytes),
                duration_seconds=duration,
                elapsed_seconds=elapsed,
            )

            if return_format in {"raw", "raw_wav", "wav"}:
                self.send_audio(output_path, "audio/wav")
                return

            self.send_json(
                {
                    "ok": True,
                    "request_id": request_id,
                    "job_id": job_id,
                    "engine": engine,
                    "mime_type": "audio/wav",
                    "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                    "duration_seconds": duration,
                    "output_bytes": len(audio_bytes),
                    "elapsed_seconds": elapsed,
                    "job": minimal_job_payload(final_job),
                }
            )

        except Exception as exc:
            log_event(
                "error",
                "exception",
                "Bridge request failed",
                request_id=request_id,
                origin=self.headers.get("Origin", ""),
                error=str(exc),
                elapsed_seconds=round(time.time() - started, 3),
            )
            self.send_json({"ok": False, "request_id": request_id, "error": str(exc)}, 400)


def main() -> int:
    parser = argparse.ArgumentParser(description="HandAISpoke TTS AI Studio Bridge")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    ensure_dirs()
    print("HandAISpoke TTS AI Studio Bridge")
    print(f"Bridge version: {VERSION}")
    print(f"Bridge: http://{args.host}:{args.port}")
    print(f"TTS WebUI: {WEBUI_BASE}")
    print(f"Log: {BRIDGE_LOG}")
    print("Token configured:", "yes" if TOKEN else "NO - set TTS_AI_STUDIO_BRIDGE_TOKEN before tunneling")
    print("Local TTS bridge active: cloned/custom voice generation is handled by your configured local TTS engine, not Gemini.")
    if not TOKEN:
        print("Refusing to start without TTS_AI_STUDIO_BRIDGE_TOKEN.")
        return 2

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nBridge stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
