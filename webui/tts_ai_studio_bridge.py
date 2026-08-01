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
import cgi
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


VERSION = "0.91"

LAB = Path(os.environ.get("TTS_LAB", "/home/user/tts-lab"))
OUT_DIR = Path(os.environ.get("TTS_OUT", str(LAB / "output")))
REF_DIR = Path(os.environ.get("TTS_REF", str(LAB / "references")))
BRIDGE_REF_DIR = Path(os.environ.get("TTS_AI_STUDIO_BRIDGE_REF_DIR", str(REF_DIR / "ai_studio_bridge")))
BRIDGE_OUT_DIR = Path(os.environ.get("TTS_AI_STUDIO_BRIDGE_OUT_DIR", str(OUT_DIR / "ai_studio_bridge")))
STT_UPLOAD_DIR = Path(os.environ.get("TTS_STT_UPLOAD_DIR", str(LAB / "stt_uploads")))
BRIDGE_STT_DIR = Path(os.environ.get("TTS_AI_STUDIO_BRIDGE_STT_DIR", str(STT_UPLOAD_DIR / "ai_studio_bridge")))
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

ALLOWED_STT_ENGINES = {
    x.strip().lower()
    for x in os.environ.get("TTS_AI_STUDIO_BRIDGE_ALLOWED_STT_ENGINES", "whisper-1,faster-whisper,whisperx,local-whisperx,whisperx-diarization,local-whisperx-diarize").split(",")
    if x.strip()
}

MAX_TEXT_CHARS = int(os.environ.get("TTS_AI_STUDIO_BRIDGE_MAX_TEXT_CHARS", "1200"))
MAX_REF_BYTES = int(os.environ.get("TTS_AI_STUDIO_BRIDGE_MAX_REF_BYTES", str(20 * 1024 * 1024)))
MAX_STT_BYTES = int(os.environ.get("TTS_AI_STUDIO_BRIDGE_MAX_STT_BYTES", str(250 * 1024 * 1024)))
DEFAULT_STT_TIMEOUT_SECONDS = float(os.environ.get("TTS_AI_STUDIO_BRIDGE_STT_TIMEOUT_SECONDS", "600"))
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("TTS_AI_STUDIO_BRIDGE_TIMEOUT_SECONDS", "90"))
POLL_INTERVAL_SECONDS = float(os.environ.get("TTS_AI_STUDIO_BRIDGE_POLL_INTERVAL_SECONDS", "0.5"))

SAFE_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")
VALID_RETURN_FORMATS = {"json", "json_base64", "base64", "raw", "raw_wav", "wav"}
VALID_MODES = {"sync", "async"}
VALID_TRANSCRIPTION_FORMATS = {"json", "verbose_json", "text"}
SPEECH_ENGINE_ALIASES = {
    "whisper-1": "faster-whisper",
    "faster-whisper": "faster-whisper",
    "local-faster-whisper": "faster-whisper",
    "whisperx": "whisperx",
    "local-whisperx": "whisperx",
    "whisperx-diarization": "whisperx-diarization",
    "whisperx-diarize": "whisperx-diarization",
    "local-whisperx-diarize": "whisperx-diarization",
}


def ensure_dirs() -> None:
    BRIDGE_REF_DIR.mkdir(parents=True, exist_ok=True)
    BRIDGE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    BRIDGE_STT_DIR.mkdir(parents=True, exist_ok=True)
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
        "source_path",
        "output",
        "transcript",
    }
    out = {k: job.get(k) for k in keep if k in job and job.get(k) is not None}
    if job.get("kind") in {"speech-api", "stt", "speech-analysis"} and job.get("result") is not None:
        out["result"] = job.get("result")
    return out


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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-HandAISpoke-Bridge-Token")
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

    def send_text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        raw = str(text or "").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
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
        auth = self.headers.get("Authorization", "")
        if not supplied and auth.lower().startswith("bearer "):
            supplied = auth.split(" ", 1)[1].strip()
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


    def public_url(self, path: str) -> str:
        host = self.headers.get("Host", "")
        proto = self.headers.get("X-Forwarded-Proto", "") or ("https" if host and not host.startswith("127.0.0.1") and not host.startswith("localhost") else "http")
        return f"{proto}://{host}{path}" if host else path

    def read_multipart_form(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype.lower():
            raise ValueError("multipart/form-data is required")
        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": ctype,
            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
        }
        return cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=environ, keep_blank_values=True)

    def form_value(self, form, name: str, default: str = "") -> str:
        if name not in form:
            return default
        item = form[name]
        if isinstance(item, list):
            item = item[0] if item else None
        if item is None:
            return default
        return str(getattr(item, "value", default) or default)

    def form_values(self, form, name: str) -> list[str]:
        if name not in form:
            return []
        item = form[name]
        items = item if isinstance(item, list) else [item]
        vals: list[str] = []
        for it in items:
            val = str(getattr(it, "value", "") or "").strip()
            if val:
                vals.append(val)
        return vals

    def form_file(self, form, name: str) -> tuple[str, str, bytes]:
        if name not in form:
            raise ValueError(f"{name} file field is required")
        item = form[name]
        if isinstance(item, list):
            item = item[0]
        filename = safe_slug(Path(getattr(item, "filename", "") or "audio").name, "audio")
        mime = str(getattr(item, "type", "") or "application/octet-stream")
        data = item.file.read() if getattr(item, "file", None) else b""
        if not data:
            raise ValueError("uploaded audio file was empty")
        if len(data) > MAX_STT_BYTES:
            raise ValueError(f"uploaded audio is too large: {len(data)} bytes > {MAX_STT_BYTES}")
        return filename, mime, data

    def save_stt_audio(self, request_id: str, filename: str, mime: str, data: bytes) -> Path:
        if not data:
            raise ValueError("audio decoded to zero bytes")
        if len(data) > MAX_STT_BYTES:
            raise ValueError(f"audio is too large: {len(data)} bytes > {MAX_STT_BYTES}")
        ext = Path(filename).suffix.lower() or ext_from_mime(mime)
        if ext not in {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".aac"}:
            ext = ext_from_mime(mime)
        target = BRIDGE_STT_DIR / f"{safe_slug(request_id)}_{hashlib.sha256(data).hexdigest()[:12]}{ext}"
        target.write_bytes(data)
        return target

    def normalize_speech_engine(self, value: str, diarize: bool = False) -> str:
        raw = str(value or "faster-whisper").strip().lower()
        if raw not in ALLOWED_STT_ENGINES:
            raise ValueError(f"speech model/engine is not allowed for bridge mode: {raw}")
        engine = SPEECH_ENGINE_ALIASES.get(raw, raw)
        if engine == "whisperx" and diarize:
            engine = "whisperx-diarization"
        if engine not in {"faster-whisper", "whisperx", "whisperx-diarization"}:
            raise ValueError(f"unsupported speech engine: {value}")
        return engine

    def queue_speech_job(self, request_id: str, source_path: Path, body: dict, openai_model: str = "") -> tuple[str, dict, dict]:
        diarize = bool(body.get("diarization") or body.get("diarize"))
        model_value = str(openai_model or body.get("engine") or body.get("model") or "faster-whisper")
        engine = self.normalize_speech_engine(model_value, diarize)
        whisper_model = str(body.get("model_size") or body.get("whisper_model") or body.get("model_name") or "").strip().lower()
        if not whisper_model:
            whisper_model = "small" if engine.startswith("whisperx") else "base"
        payload = {
            "source_path": str(source_path),
            "engine": engine,
            "model": engine,
            "model_size": whisper_model,
            "device": str(body.get("device") or "auto"),
            "compute_type": str(body.get("compute_type") or "auto"),
            "language": str(body.get("language") or "auto"),
            "word_timestamps": body.get("word_timestamps", True),
            "diarization": engine == "whisperx-diarization" or diarize,
            "batch_size": int(body.get("batch_size") or 2),
            "timeout_seconds": int(float(body.get("timeout_seconds") or DEFAULT_STT_TIMEOUT_SECONDS)),
            "source": "handaispoke-ai-studio-bridge",
            "bridge_request_id": request_id,
        }
        queued = webui_request("POST", "/api/speech/transcribe", payload, timeout=20)
        job = queued.get("job") or {}
        job_id = job.get("id")
        if not job_id:
            raise RuntimeError(f"TTS WebUI did not return a speech job id: {queued}")
        return job_id, job, payload

    def openai_transcription_payload(self, result: dict, response_format: str) -> dict | str:
        text = str(result.get("text") or "")
        if response_format == "text":
            return text
        if response_format == "json":
            return {"text": text}
        return {
            "task": "transcribe",
            "language": result.get("language") or "en",
            "duration": result.get("duration") or result.get("duration_seconds"),
            "text": text,
            "segments": result.get("segments") or [],
            "words": result.get("words") or [],
        }

    def send_speech_result(self, request_id: str, job_id: str, job: dict, response_format: str, openai_compatible: bool = False) -> None:
        status = job.get("status")
        if status != "done":
            self.send_json({
                "ok": False,
                "request_id": request_id,
                "job_id": job_id,
                "status": status,
                "status_path": f"/api/ai-studio-bridge/jobs/{job_id}",
                "status_url": self.public_url(f"/api/ai-studio-bridge/jobs/{job_id}"),
                "error": job.get("error") or "speech job did not complete before timeout",
                "job": minimal_job_payload(job),
            }, 202 if status not in {"error", "canceled"} else 500)
            return
        result = job.get("result") or {}
        if openai_compatible:
            payload = self.openai_transcription_payload(result, response_format)
            if isinstance(payload, str):
                self.send_text(payload)
            else:
                self.send_json(payload)
            return
        self.send_json({
            "ok": True,
            "request_id": request_id,
            "job_id": job_id,
            "status": "done",
            "text": result.get("text") or job.get("transcript") or "",
            "result": result,
            "job": minimal_job_payload(job),
        })

    def handle_bridge_transcribe(self) -> None:
        if not self.require_auth():
            return
        started = time.time()
        request_id = ""
        try:
            ensure_dirs()
            body = self.read_json_body()
            request_id = safe_slug(str(body.get("request_id") or uuid.uuid4().hex))
            mode = str(body.get("mode") or "async").strip().lower()
            if mode not in VALID_MODES:
                raise ValueError(f"mode is not supported: {mode}")
            if body.get("source_path"):
                source_path = Path(str(body.get("source_path"))).expanduser()
            else:
                audio_b64 = str(body.get("audio_base64") or body.get("data_base64") or "").strip()
                if not audio_b64:
                    raise ValueError("audio_base64 is required unless source_path is supplied")
                audio_bytes = decode_b64(audio_b64)
                filename = str(body.get("filename") or "bridge-speech.wav")
                mime = str(body.get("audio_mime_type") or body.get("mime_type") or "audio/wav")
                source_path = self.save_stt_audio(request_id, filename, mime, audio_bytes)
            job_id, job, payload = self.queue_speech_job(request_id, source_path, body)
            log_event("info", "speech-queued", "Speech job queued", request_id=request_id, job_id=job_id, engine=payload.get("engine"), source_path=str(source_path), mode=mode)
            if mode == "async":
                self.send_json({
                    "ok": True,
                    "request_id": request_id,
                    "job_id": job_id,
                    "engine": payload.get("engine"),
                    "status": "queued",
                    "status_path": f"/api/ai-studio-bridge/jobs/{job_id}",
                    "status_url": self.public_url(f"/api/ai-studio-bridge/jobs/{job_id}"),
                    "job": minimal_job_payload(job),
                }, 202)
                return
            final_job = wait_for_job(job_id, float(body.get("timeout_seconds") or DEFAULT_STT_TIMEOUT_SECONDS))
            log_event("info", "speech-complete", "Speech sync wait finished", request_id=request_id, job_id=job_id, status=final_job.get("status"), elapsed_seconds=round(time.time() - started, 3))
            self.send_speech_result(request_id, job_id, final_job, str(body.get("response_format") or "verbose_json"), openai_compatible=False)
        except Exception as exc:
            log_event("error", "speech-exception", "Bridge speech request failed", request_id=request_id, error=str(exc), elapsed_seconds=round(time.time() - started, 3))
            self.send_json({"ok": False, "request_id": request_id, "error": str(exc)}, 400)

    def handle_openai_transcription(self) -> None:
        if not self.require_auth():
            return
        started = time.time()
        request_id = ""
        try:
            ensure_dirs()
            form = self.read_multipart_form()
            request_id = safe_slug(self.form_value(form, "request_id", uuid.uuid4().hex))
            filename, mime, data = self.form_file(form, "file")
            source_path = self.save_stt_audio(request_id, filename, mime, data)
            model = self.form_value(form, "model", "whisper-1")
            response_format = self.form_value(form, "response_format", "json").strip().lower()
            if response_format not in VALID_TRANSCRIPTION_FORMATS:
                response_format = "json"
            granularities = self.form_values(form, "timestamp_granularities[]") + self.form_values(form, "timestamp_granularities")
            body = {
                "mode": self.form_value(form, "mode", "sync"),
                "language": self.form_value(form, "language", "auto"),
                "device": self.form_value(form, "device", "auto"),
                "compute_type": self.form_value(form, "compute_type", "auto"),
                "model_size": self.form_value(form, "model_size", ""),
                "word_timestamps": ("word" in granularities) or response_format == "verbose_json",
                "diarization": "diarization" in model.lower() or self.form_value(form, "diarization", "").lower() in {"1", "true", "yes", "on"},
                "timeout_seconds": float(self.form_value(form, "timeout_seconds", str(DEFAULT_STT_TIMEOUT_SECONDS))),
            }
            job_id, job, payload = self.queue_speech_job(request_id, source_path, body, openai_model=model)
            mode = str(body.get("mode") or "sync").lower()
            log_event("info", "openai-speech-queued", "OpenAI-compatible speech job queued", request_id=request_id, job_id=job_id, model=model, engine=payload.get("engine"), mode=mode)
            if mode == "async":
                self.send_json({
                    "ok": True,
                    "request_id": request_id,
                    "job_id": job_id,
                    "status": "queued",
                    "status_path": f"/api/ai-studio-bridge/jobs/{job_id}",
                    "status_url": self.public_url(f"/api/ai-studio-bridge/jobs/{job_id}"),
                }, 202)
                return
            final_job = wait_for_job(job_id, float(body.get("timeout_seconds") or DEFAULT_STT_TIMEOUT_SECONDS))
            log_event("info", "openai-speech-complete", "OpenAI-compatible speech sync wait finished", request_id=request_id, job_id=job_id, status=final_job.get("status"), elapsed_seconds=round(time.time() - started, 3))
            self.send_speech_result(request_id, job_id, final_job, response_format, openai_compatible=True)
        except Exception as exc:
            log_event("error", "openai-speech-exception", "OpenAI-compatible speech request failed", request_id=request_id, error=str(exc), elapsed_seconds=round(time.time() - started, 3))
            self.send_json({"error": {"message": str(exc), "type": "handai_bridge_error"}}, 400)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/ai-studio-bridge/status":
            if not self.require_auth():
                return
            try:
                meta = webui_request("GET", "/api/meta", timeout=5)
                try:
                    speech = webui_request("GET", "/api/speech/status", timeout=8)
                except Exception as speech_exc:
                    speech = {"ok": False, "error": str(speech_exc)}
                self.send_json(
                    {
                        "ok": True,
                        "bridge": "handaispoke-ai-studio-bridge",
                        "bridge_version": VERSION,
                        "webui_base": WEBUI_BASE,
                        "webui_version": meta.get("version"),
                        "allowed_engines": sorted(ALLOWED_ENGINES),
                        "allowed_stt_engines": sorted(ALLOWED_STT_ENGINES),
                        "max_text_chars": MAX_TEXT_CHARS,
                        "max_reference_bytes": MAX_REF_BYTES,
                        "max_stt_bytes": MAX_STT_BYTES,
                        "speech_api": speech,
                        "routes": {
                            "clone_tts": "/api/ai-studio-bridge/clone-tts",
                            "transcribe": "/api/ai-studio-bridge/transcribe",
                            "openai_transcriptions": "/v1/audio/transcriptions",
                            "jobs": "/api/ai-studio-bridge/jobs/<job_id>",
                        },
                        "log_path": str(BRIDGE_LOG),
                        "message": "Local bridge active: TTS and speech transcription are handled by configured local engines, not Gemini.",
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

        if path == "/api/ai-studio-bridge/transcribe":
            self.handle_bridge_transcribe()
            return
        if path == "/v1/audio/transcriptions":
            self.handle_openai_transcription()
            return
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
    print("Local AI Studio bridge active: cloned/custom TTS and speech transcription are handled by local engines, not Gemini.")
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
