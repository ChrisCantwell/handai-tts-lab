#!/usr/bin/env python3
"""
Unified local web interface for /home/user/tts-lab voice/TTS engines.

Version 0.86 adds public-alpha stack status diagnostics in Maintenance while keeping the stack installer separate from the Web UI installer.

No third-party Python dependencies. It calls Grok's existing tts-lab.sh wrapper,
which keeps each model in its own conda environment.
"""
from __future__ import annotations

import base64
import html
import array
import math
import json
import mimetypes
import os
import queue
import re
import shlex
import shutil
import subprocess
import signal
import threading
import time
import uuid
import wave
import sys
import zipfile
from dataclasses import asdict, dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

LAB = Path(os.environ.get("TTS_LAB", "/home/user/tts-lab"))
LAUNCHER = Path(os.environ.get("TTS_LAUNCHER", str(LAB / "tts-lab.sh")))
OUT_DIR = Path(os.environ.get("TTS_OUT", str(LAB / "output")))
REF_DIR = Path(os.environ.get("TTS_REF", str(LAB / "references")))
PROFILE_DIR = Path(os.environ.get("TTS_PROFILE_DIR", str(REF_DIR / "profiles")))
JOB_DIR = Path(os.environ.get("TTS_JOB_DIR", str(OUT_DIR / "job_history")))
CONFIG_DIR = Path(os.environ.get("TTS_CONFIG_DIR", str(LAB / "config")))
WEBUI_STATE = CONFIG_DIR / "webui_state.json"
UI_DIAGNOSTICS_DIR = Path(os.environ.get("TTS_UI_DIAGNOSTICS_DIR", str(LAB / "logs" / "ui-diagnostics")))
EXTERNAL_ACTION_LOG = UI_DIAGNOSTICS_DIR / "external-actions.log"
HF_TOKEN_FILE = CONFIG_DIR / "huggingface_token"
STT_UPLOAD_DIR = Path(os.environ.get("TTS_STT_UPLOAD_DIR", str(LAB / "stt_uploads")))
AUDIO_LAB_DIR = Path(os.environ.get("TTS_AUDIO_LAB_DIR", str(OUT_DIR / "audio_lab")))
VIDEO_INTAKE_DIR = Path(os.environ.get("TTS_VIDEO_INTAKE_DIR", str(OUT_DIR / "video_intake")))
VIDEO_SOURCE_DIR = VIDEO_INTAKE_DIR / "source_media"
VIDEO_UPLOAD_DIR = VIDEO_SOURCE_DIR / "uploads"
VIDEO_EXTRACT_DIR = VIDEO_INTAKE_DIR / "extracted_audio"
VIDEO_URL_WORK_DIR = VIDEO_SOURCE_DIR / "url_imports"
VIDEO_DL_DIR = Path(os.environ.get("TTS_VIDEO_DL_DIR", "/home/user/video-dl"))
VIDEO_DL_CMD = os.environ.get("TTS_VIDEO_DL_CMD", "").strip()
RESEMBLE_ROOT = Path(os.environ.get("TTS_RESEMBLE_ROOT", str(LAB / "engines" / "resemble-enhance")))
RESEMBLE_OUTPUT_DIR = Path(os.environ.get("TTS_RESEMBLE_OUTPUT_DIR", str(OUT_DIR / "resemble_enhance")))
RESEMBLE_INPUT_DIR = Path(os.environ.get("TTS_RESEMBLE_INPUT_DIR", str(LAB / "resemble_uploads")))
RESEMBLE_INSTALLER = Path(os.environ.get("TTS_RESEMBLE_INSTALLER", str(LAB / "install-resemble-enhance.sh")))
RESEMBLE_CMD = os.environ.get("TTS_RESEMBLE_CMD", "").strip()
RESEMBLE_COMPAT_LAUNCHER = Path(os.environ.get("TTS_RESEMBLE_COMPAT_LAUNCHER", str(RESEMBLE_ROOT / "resemble-enhance-webui")))
RESEMBLE_COMPAT_WRAPPER = Path(os.environ.get("TTS_RESEMBLE_COMPAT_WRAPPER", str(RESEMBLE_ROOT / "resemble_enhance_webui_wrapper.py")))
WHISPER_HELPER = Path(os.environ.get("TTS_WHISPER_HELPER", str(LAB / "webui" / "stt_faster_whisper.py")))
WHISPER_PYTHON = Path(os.environ.get("TTS_WHISPER_PYTHON", str(Path.home() / "miniconda3" / "envs" / "tts-whisper" / "bin" / "python")))
WHISPER_CUDA_INSTALLER = Path(os.environ.get("TTS_WHISPER_CUDA_INSTALLER", str(LAB / "install-whisper-cuda-libs.sh")))
CONDA_ROOT = Path(os.environ.get("CONDA_ROOT", str(Path.home() / "miniconda3")))
STACK_INSTALLER = Path(os.environ.get("TTS_STACK_INSTALLER", str(LAB / "stack-installer" / "install-tts-lab-stack.sh")))
STACK_INSTALLER_ENV = os.environ.get("TTS_STACK_INSTALLER", "").strip()
ENGINE_ENV_NAMES = {"chatterbox": "tts-chatterbox", "qwen3": "tts-qwen3", "cosyvoice": "tts-cosyvoice", "f5": "tts-f5"}
DEFAULT_REF = REF_DIR / "voice_ref.wav"
HOST = os.environ.get("TTS_WEBUI_HOST", "127.0.0.1")
PORT = int(os.environ.get("TTS_WEBUI_PORT", "7870"))

VERSION = "0.86"
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv"}
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS
TEXT_EXTS = {".txt", ".md", ".text", ".json"}

ENGINE_META = {
    "chatterbox": {
        "label": "Chatterbox-Turbo",
        "status": "working",
        "note": "Best first pick for the RTX 2060 setup. Transcript optional.",
    },
    "qwen3": {
        "label": "Qwen3-TTS 0.6B",
        "status": "working",
        "note": "Use x-vector-only when you do not have exact reference transcript.",
    },
    "cosyvoice": {
        "label": "CosyVoice 3",
        "status": "working-slow",
        "note": "Working but slow on 6GB VRAM. Reference transcript helps.",
    },
    "f5": {
        "label": "F5-TTS",
        "status": "broken-in-log",
        "note": "Experimental/back-burnered locally: current tests still segfault. Use Chatterbox, Qwen3, or CosyVoice first.",
    },
}

SAFE_NAME = re.compile(r"[^A-Za-z0-9_. -]+")
SAFE_SLUG = re.compile(r"[^A-Za-z0-9_.-]+")
ROLE_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_ -]{0,31})\s*:\s*(.+?)\s*$")


def now() -> float:
    return time.time()


def iso_time(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts or now()))


def safe_filename(value: str, fallback: str = "file") -> str:
    value = SAFE_NAME.sub("_", Path(value.strip()).name).strip("._- ")
    return value[:120] or fallback


def safe_slug(value: str, fallback: str = "item") -> str:
    value = SAFE_SLUG.sub("-", value.strip().lower()).strip("._-")
    return value[:80] or fallback


def ensure_dirs() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REF_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    STT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_LAB_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_INTAKE_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_URL_WORK_DIR.mkdir(parents=True, exist_ok=True)
    RESEMBLE_ROOT.mkdir(parents=True, exist_ok=True)
    RESEMBLE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESEMBLE_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    UI_DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)


def unique_wav(prefix: str) -> Path:
    ensure_dirs()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return OUT_DIR / f"{safe_slug(prefix)}_{stamp}_{uuid.uuid4().hex[:8]}.wav"


def file_version(path: Path) -> str:
    """Return a cache-busting key that changes whenever the file changes."""
    try:
        st = path.stat()
        return f"{st.st_size}-{st.st_mtime_ns}"
    except OSError:
        return str(int(time.time() * 1000))


def versioned_url(url: str, path: Path) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={file_version(path)}"

def audio_duration_seconds(path: Path) -> float | None:
    """Best-effort duration for local audio files. WAV uses stdlib; other formats use ffprobe if available."""
    try:
        if not path.exists() or not path.is_file():
            return None
        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as wf:
                rate = wf.getframerate() or 0
                frames = wf.getnframes() or 0
                return (frames / float(rate)) if rate else None
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return float(proc.stdout.strip())
    except Exception:
        return None
    return None


def audio_url_for(path: Path, base: Path = OUT_DIR) -> str:
    try:
        rel = path.relative_to(base)
        raw = "/audio/" + "/".join(rel.parts)
    except ValueError:
        raw = f"/audio/{path.name}"
    return versioned_url(raw, path)


def preview_path_for(path: Path) -> Path:
    # Keep the preview next to the WAV. Example: output.wav.preview.mp3
    return path.with_suffix(path.suffix + ".preview.mp3")


def preview_url_for(path: Path, base: Path = OUT_DIR) -> str:
    try:
        rel = path.relative_to(base)
        raw = "/preview-audio/" + "/".join(rel.parts)
    except ValueError:
        raw = f"/preview-audio/{path.name}"
    preview = preview_path_for(path)
    return versioned_url(raw, preview if preview.exists() else path)


def ensure_mp3_preview(path: Path, log_cb=None) -> Path | None:
    """Create a browser-friendly MP3 preview for an output audio file.

    Browser WAV playback has proven inconsistent on some generated files even
    when VLC plays the WAV correctly. Keep the WAV as the authoritative
    downloadable file, but feed HTML5 audio a small MP3 preview.
    """
    if not path.exists() or not path.is_file():
        return None
    if path.suffix.lower() not in AUDIO_EXTS:
        return None
    preview = preview_path_for(path)
    try:
        if preview.exists() and preview.stat().st_mtime_ns >= path.stat().st_mtime_ns and preview.stat().st_size > 0:
            return preview
    except OSError:
        pass
    # Use a temp filename that still ends in .mp3. ffmpeg infers muxers
    # from the extension unless -f is supplied; foo.mp3.tmp can fail with
    # "Unable to find a suitable output format" on some builds.
    tmp = preview.with_name(preview.name + ".tmp.mp3")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-vn", "-ar", "44100", "-ac", "1", "-b:a", "128k",
        "-f", "mp3", str(tmp),
    ]
    if log_cb:
        log_cb("\n$ " + shlex.join(cmd) + "\n")
    proc = subprocess.run(cmd, cwd=str(LAB), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.stdout and log_cb:
        log_cb(proc.stdout)
    if proc.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        tmp.replace(preview)
        if log_cb:
            log_cb("Created MP3 browser preview for inline playback.\n")
        return preview
    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass
    if log_cb:
        log_cb(f"Warning: MP3 browser preview generation failed with exit code {proc.returncode}; inline playback may still use WAV fallback.\n")
    return None


def split_synthesis_text(text: str, max_chars: int = 140) -> list[str]:
    """Split text into short, speech-friendly chunks.

    This is mainly a workaround for local engines that sometimes stop after the
    first sentence. It also keeps individual synth calls smaller for a 6GB GPU.
    """
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return []
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()] or [text]
    chunks: list[str] = []
    for sent in sentences:
        if len(sent) <= max_chars:
            chunks.append(sent)
            continue
        parts = [x.strip() for x in re.split(r"(?<=[,;:])\s+", sent) if x.strip()]
        buf = ""
        for part in parts:
            if not buf:
                buf = part
            elif len(buf) + 1 + len(part) <= max_chars:
                buf += " " + part
            else:
                chunks.append(buf)
                buf = part
        if buf:
            chunks.append(buf)
    return chunks or [text]


def oom_message(rc: int | None) -> str:
    if rc in (137, -9):
        return "Command was killed by the OS, probably system RAM/VRAM pressure. Close other heavy apps, restart the web UI, and try a shorter line or a lighter engine."
    return f"Command failed with exit code {rc}"


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON body: {exc}") from exc


def decode_b64(data_url_or_b64: str) -> bytes:
    data = str(data_url_or_b64 or "")
    if "," in data and data.strip().lower().startswith("data:"):
        data = data.split(",", 1)[1]
    raw = base64.b64decode(data)
    if not raw:
        raise ValueError("No file data provided.")
    return raw


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe_existing_path(value: str, allowed_roots: list[Path], must_exist: bool = True) -> Path:
    if not value:
        raise ValueError("Path is required.")
    path = Path(value).expanduser().resolve()
    if must_exist and not path.exists():
        raise ValueError(f"File not found: {path}")
    if not any(inside(path, root) for root in allowed_roots):
        raise ValueError(f"Path outside allowed directories: {path}")
    return path



def media_action_roots() -> list[Path]:
    return [REF_DIR, OUT_DIR, PROFILE_DIR, STT_UPLOAD_DIR, AUDIO_LAB_DIR, VIDEO_INTAKE_DIR, RESEMBLE_INPUT_DIR, RESEMBLE_OUTPUT_DIR]


def append_external_action_log(message: str, data: dict[str, Any] | None = None) -> None:
    ensure_dirs()
    try:
        line = f"{iso_time()} {message}"
        if data:
            line += " " + json.dumps(data, sort_keys=True, default=str)
        with EXTERNAL_ACTION_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass



def command_probe(name: str) -> dict[str, Any]:
    path = shutil.which(name) or ""
    return {"name": name, "path": path, "available": bool(path)}


def path_probe(path: Path, executable: bool = False) -> dict[str, Any]:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
        "executable": bool(exists and os.access(path, os.X_OK)) if executable else None,
    }


def stack_installer_candidates() -> list[Path]:
    candidates: list[Path] = []
    if STACK_INSTALLER_ENV:
        candidates.append(Path(STACK_INSTALLER_ENV).expanduser())
    candidates.extend([
        STACK_INSTALLER,
        LAB / "install-tts-lab-stack.sh",
        LAB / "stack-installer" / "install-tts-lab-stack.sh",
        Path(__file__).resolve().parent.parent / "stack-installer" / "install-tts-lab-stack.sh",
        Path.cwd() / "stack-installer" / "install-tts-lab-stack.sh",
        Path.home() / "handai-tts-lab" / "stack-installer" / "install-tts-lab-stack.sh",
    ])
    seen: set[str] = set()
    unique: list[Path] = []
    for c in candidates:
        try:
            key = str(c.expanduser().resolve())
        except Exception:
            key = str(c)
        if key not in seen:
            seen.add(key)
            unique.append(c.expanduser())
    return unique


def detect_stack_installer_version(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:20000]
    except Exception:
        return ""
    m = re.search(r'^VERSION=["\']([^"\']+)["\']', text, re.MULTILINE)
    if m:
        return m.group(1)
    m = re.search(r'TTS Lab Stack Installer v([0-9][A-Za-z0-9_.-]*)', text)
    return m.group(1) if m else ""


def launcher_status_payload() -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": str(LAUNCHER),
        "exists": LAUNCHER.exists(),
        "executable": bool(LAUNCHER.exists() and os.access(LAUNCHER, os.X_OK)),
        "status_ran": False,
        "status_ok": False,
        "returncode": None,
        "output_tail": "",
        "error": "",
    }
    if not data["exists"]:
        data["error"] = "Launcher is missing. Run the stack installer or set TTS_LAUNCHER."
        return data
    if not data["executable"]:
        data["error"] = "Launcher exists but is not executable."
        return data
    try:
        proc = subprocess.run([str(LAUNCHER), "status"], cwd=str(LAB), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
        data["status_ran"] = True
        data["returncode"] = proc.returncode
        data["status_ok"] = proc.returncode == 0
        data["output_tail"] = (proc.stdout or "")[-4000:]
        if proc.returncode != 0:
            data["error"] = f"launcher status exited {proc.returncode}"
    except Exception as exc:
        data["error"] = str(exc)
    return data


def engine_env_status_payload() -> dict[str, Any]:
    envs: dict[str, Any] = {}
    for engine, env_name in ENGINE_ENV_NAMES.items():
        env_path = CONDA_ROOT / "envs" / env_name
        py = env_path / "bin" / "python"
        envs[engine] = {
            "env_name": env_name,
            "path": str(env_path),
            "exists": env_path.exists(),
            "python": str(py),
            "python_exists": py.exists(),
            "green_path": engine in {"chatterbox", "qwen3", "cosyvoice"},
            "experimental": engine == "f5",
        }
    return envs


def stack_status_payload() -> dict[str, Any]:
    installer_candidates = []
    best_installer: dict[str, Any] | None = None
    for candidate in stack_installer_candidates():
        item = path_probe(candidate, executable=True)
        item["version"] = detect_stack_installer_version(candidate) if item.get("exists") else ""
        installer_candidates.append(item)
        if best_installer is None and item.get("exists"):
            best_installer = item

    video_status = video_intake_status_payload()
    external_status = external_command_status()
    helpers = {
        "conda": {"path": str(CONDA_ROOT / "bin" / "conda"), "available": (CONDA_ROOT / "bin" / "conda").exists()},
        "ffmpeg": command_probe("ffmpeg"),
        "ffprobe": command_probe("ffprobe"),
        "yt_dlp": command_probe("yt-dlp"),
        "git": command_probe("git"),
        "git_lfs": command_probe("git-lfs"),
        "nvidia_smi": command_probe("nvidia-smi"),
        "audacity": external_status.get("audacity", {}),
        "xdg_open": command_probe("xdg-open"),
    }
    launcher = launcher_status_payload()
    engines = engine_env_status_payload()
    green_engines = [k for k, v in engines.items() if v.get("green_path")]
    green_ready = all(engines[k].get("exists") and engines[k].get("python_exists") for k in green_engines)
    ready = bool(launcher.get("exists") and launcher.get("executable") and green_ready)
    return {
        "version": VERSION,
        "lab": str(LAB),
        "launcher": launcher,
        "stack_installer": {
            "best": best_installer or {},
            "candidates": installer_candidates,
            "env_var": "TTS_STACK_INSTALLER",
        },
        "conda_root": str(CONDA_ROOT),
        "engines": engines,
        "helpers": helpers,
        "video_downloader": video_status,
        "external_actions": external_status,
        "logs": {
            "ui_diagnostics": str(UI_DIAGNOSTICS_DIR),
            "external_actions": str(EXTERNAL_ACTION_LOG),
            "stack_installer": str(LAB / "logs" / "stack-installer"),
            "jobs": str(JOB_DIR),
        },
        "ready": ready,
        "notes": [
            "This is a diagnostics-only Web UI check. It does not install engines or run repair actions.",
            "Green path engines are Chatterbox, Qwen3, and CosyVoice. F5 is present/experimental when detected.",
            "If launcher status fails but the launcher exists, copy the diagnostics and inspect the stack-installer logs.",
        ],
    }


def external_command_status() -> dict[str, Any]:
    audacity_cmd = os.environ.get("TTS_AUDACITY_CMD", "").strip()
    xdg_open = shutil.which("xdg-open") or ""
    return {
        "audacity": {
            "configured": bool(audacity_cmd),
            "command": audacity_cmd or (shutil.which("audacity") or ""),
            "available": bool(audacity_cmd or shutil.which("audacity")),
            "env_var": "TTS_AUDACITY_CMD",
        },
        "system_default": {
            "command": xdg_open,
            "available": bool(xdg_open),
        },
        "containing_folder": {
            "command": xdg_open,
            "available": bool(xdg_open),
        },
        "log_path": str(EXTERNAL_ACTION_LOG),
    }


def launch_external_target(target: str, path_value: str) -> dict[str, Any]:
    target = (target or "").strip().lower().replace("_", "-")
    src = safe_existing_path(path_value, media_action_roots())
    status = external_command_status()
    if target == "audacity":
        audacity_env = os.environ.get("TTS_AUDACITY_CMD", "").strip()
        if audacity_env:
            cmd = shlex.split(audacity_env) + [str(src)]
        else:
            exe = shutil.which("audacity")
            if not exe:
                raise RuntimeError("Audacity was not found. Install audacity or set TTS_AUDACITY_CMD to the launch command.")
            cmd = [exe, str(src)]
        label = "Audacity"
    elif target in {"system-default", "default", "xdg-open"}:
        exe = status["system_default"].get("command") or ""
        if not exe:
            raise RuntimeError("xdg-open was not found, so the system default app cannot be launched.")
        cmd = [exe, str(src)]
        label = "system default app"
    elif target in {"containing-folder", "folder", "open-folder"}:
        exe = status["containing_folder"].get("command") or ""
        if not exe:
            raise RuntimeError("xdg-open was not found, so the containing folder cannot be opened.")
        cmd = [exe, str(src.parent)]
        label = "containing folder"
    else:
        raise ValueError(f"Unknown external launch target: {target}")
    append_external_action_log("external launch requested", {"target": target, "path": str(src), "command": cmd})
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
    return {"ok": True, "target": target, "label": label, "path": str(src), "command": cmd, "log_path": str(EXTERNAL_ACTION_LOG)}


def read_text_file_if_exists(path: Path | None) -> str:
    if not path or not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        return path.read_text(errors="replace").strip()


def read_tail_text(path: Path, max_bytes: int = 128000) -> str:
    """Read the tail of a text/log file without loading huge logs into RAM."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                data = fh.read(max_bytes)
                prefix = b"... [earlier log output omitted]\n"
                data = prefix + data
            else:
                data = fh.read()
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def companion_transcript(path: Path) -> Path | None:
    for ext in (".txt", ".md"):
        candidate = path.with_suffix(ext)
        if candidate.exists():
            return candidate
    sidecar = path.with_suffix(path.suffix + ".txt")
    if sidecar.exists():
        return sidecar
    return None


def write_output_sidecar(output: Path, payload: dict[str, Any], job: "Job", role: str | None = None) -> Path:
    meta = {
        "kind": "generated-output",
        "created_at": iso_time(),
        "job_id": job.id,
        "engine": payload.get("engine"),
        "role": role or payload.get("role"),
        "text": payload.get("text", ""),
        "reference_audio": payload.get("ref", ""),
        "reference_transcript": payload.get("ref_text", ""),
        "x_vector_only": bool(payload.get("x_vector_only", False)),
        "output_audio": str(output),
        "promoted_to_profile": False,
        "warning": "Generated audio is not automatically a reference voice. Promote explicitly if you accept clone-of-clone risk.",
    }
    sidecar = output.with_suffix(output.suffix + ".json")
    sidecar.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return sidecar


def read_output_sidecar(path: Path) -> dict[str, Any]:
    sidecar = path.with_suffix(path.suffix + ".json")
    if sidecar.exists():
        try:
            return json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}



def legacy_filename_template_from_state(state: dict[str, Any]) -> str:
    """Build a v0.75 template from older dropdown-style naming defaults."""
    custom_mode = str(state.get("global_name_mode") or "none").lower().strip()
    date_mode = str(state.get("global_date_mode") or "none").lower().strip()
    template = "[source]"
    if custom_mode == "replace" and str(state.get("global_name") or "").strip():
        template = "[custom]"
    elif custom_mode == "prefix":
        template = "[custom]-" + template
    elif custom_mode == "suffix":
        template = template + "-[custom]"
    # v0.74 had no function dropdown. Preserve the old convention exactly and
    # leave function naming disabled unless the user opts in later.
    if date_mode == "prefix":
        template = "[YYYYMMDD]-" + template
    elif date_mode == "suffix":
        template = template + "-[YYYYMMDD]"
    return template + "[version][.ext]"

def default_webui_state() -> dict[str, Any]:
    return {
        "remember_form": True,
        "engine": "chatterbox",
        "profile": "",
        "role": "EXEC",
        "ref": str(DEFAULT_REF),
        "ref_text": "",
        "text": "",
        "x_vector_only": True,
        "split_on_sentences": True,
        "ui_mode": "producer",
        "show_advanced_options": True,
        "show_profile_tools": True,
        "show_experimental_profiles": True,
        "show_metadata_buttons": True,
        "show_job_logs": True,
        "show_delete_buttons": True,
        "sticky_tabs": False,
        "panel_orientation": "side",
        "jobs_as_tab": False,
        "operations_panel_width": 560,
        "dismissed_notices": [],
        "dismiss_whisper_ready": False,
        "global_name": "",
        "global_name_mode": "none",
        "global_function_mode": "none",
        "global_date_mode": "none",
        "global_version_mode": "collision",
        "global_filename_template": "[source][version][.ext]",
        "resemble_install_mode": "auto",
        "video_format": "wav",
        "video_mp3_bitrate": "128k",
        "video_sample_rate": "unchanged",
        "video_channels": "unchanged",
        "video_normalize": True,
        "audio_lab_format": "unchanged",
        "audio_lab_mp3_bitrate": "192k",
        "audio_lab_sample_rate": "unchanged",
        "audio_lab_channels": "unchanged",
        "audio_lab_normalize": True,
    }


def read_webui_state() -> dict[str, Any]:
    ensure_dirs()
    state = default_webui_state()
    loaded: dict[str, Any] = {}
    if WEBUI_STATE.exists():
        try:
            raw = json.loads(WEBUI_STATE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                loaded = raw
                state.update({k: loaded[k] for k in state.keys() if k in loaded})
        except Exception:
            pass
    # v0.74 migration: naming defaults are now universal. If an older state file
    # only has Audio Lab naming keys, use those as the global defaults so an
    # upgrade does not silently reset the user's established convention.
    legacy_pairs = {
        "global_name": "audio_lab_name",
        "global_name_mode": "audio_lab_name_mode",
        "global_date_mode": "audio_lab_date_mode",
        "global_version_mode": "audio_lab_version_mode",
    }
    for global_key, legacy_key in legacy_pairs.items():
        if global_key not in loaded and legacy_key in loaded:
            state[global_key] = loaded[legacy_key]
    # v0.75 migration: if no manual template exists yet, build one from the
    # previous dropdown-style naming preferences. New installs default to no
    # custom/function/date naming and a compact source-based template.
    if "global_filename_template" not in loaded:
        state["global_filename_template"] = legacy_filename_template_from_state(state)
    return state


def write_webui_state(data: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    remember = bool(data.get("remember_form", True))
    if not remember:
        state = default_webui_state()
        state["remember_form"] = False
    else:
        state = default_webui_state()
        for key in state.keys():
            if key in data:
                state[key] = data[key]
        state["remember_form"] = True
    tmp = WEBUI_STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(WEBUI_STATE)
    return state


def clear_webui_state() -> dict[str, Any]:
    ensure_dirs()
    try:
        WEBUI_STATE.unlink(missing_ok=True)
    except Exception:
        pass
    return default_webui_state()


def profile_manifest(profile_dir: Path) -> dict[str, Any] | None:
    manifest = profile_dir / "voice-profile.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("slug", profile_dir.name)
    audio_name = data.get("audio_file") or "audio.wav"
    transcript_name = data.get("transcript_file") or "transcript.txt"
    audio_path = profile_dir / str(audio_name)
    transcript_path = profile_dir / str(transcript_name)
    data["audio_path"] = str(audio_path)
    data["transcript_path"] = str(transcript_path)
    data["audio_url"] = versioned_url(f"/profile-audio/{profile_dir.name}/{audio_path.name}", audio_path)
    data["transcript"] = read_text_file_if_exists(transcript_path)
    data["export_url"] = f"/profile-zip/{profile_dir.name}.zip"
    duration = audio_duration_seconds(audio_path)
    data["duration_seconds"] = duration
    data["duration_warning"] = bool(duration is not None and duration < 10.0)
    data["ok"] = audio_path.exists()
    return data


def profiles_payload() -> list[dict[str, Any]]:
    ensure_dirs()
    profiles: list[dict[str, Any]] = []
    for d in sorted(PROFILE_DIR.iterdir(), key=lambda p: p.name.lower() if p.is_dir() else ""):
        if not d.is_dir():
            continue
        m = profile_manifest(d)
        if m:
            profiles.append(m)
    return profiles


def loose_refs_payload() -> list[dict[str, Any]]:
    ensure_dirs()
    refs = []
    for p in sorted(REF_DIR.glob("*"), key=lambda x: x.name.lower()):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            transcript_path = companion_transcript(p)
            duration = audio_duration_seconds(p)
            refs.append({
                "name": p.name,
                "path": str(p),
                "size": p.stat().st_size,
                "audio_url": versioned_url("/ref-audio/" + p.name, p),
                "duration_seconds": duration,
                "duration_warning": bool(duration is not None and duration < 10.0),
                "transcript_path": str(transcript_path) if transcript_path else "",
                "transcript": read_text_file_if_exists(transcript_path),
            })
    return refs


def outputs_payload() -> list[dict[str, Any]]:
    ensure_dirs()
    files = []
    for p in sorted(OUT_DIR.rglob("*"), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True):
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXTS:
            continue
        if p.name.endswith(".preview.mp3"):
            continue
        rel = p.relative_to(OUT_DIR)
        if any(part.endswith("_parts") for part in rel.parts):
            continue
        if rel.parts and rel.parts[0] == "job_history":
            continue
        if len(rel.parts) >= 2 and rel.parts[0] == "video_intake" and rel.parts[1] in {"uploads", "url_imports", "source_media"}:
            continue
        if len(rel.parts) >= 2 and rel.parts[0] == "resemble_enhance" and rel.parts[1] in {"work"}:
            continue
        if len(files) >= 150:
            break
        meta = read_output_sidecar(p)
        duration = audio_duration_seconds(p)
        ext = p.suffix.lower().lstrip(".") or "audio"
        files.append({
            "name": str(rel),
            "path": str(p),
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
            "duration_seconds": duration,
            "audio_url": preview_url_for(p),
            "preview_url": preview_url_for(p),
            "wav_url": audio_url_for(p),
            "download_url": audio_url_for(p),
            "download_label": ext,
            "engine": meta.get("engine", ""),
            "role": meta.get("role", ""),
            "text": meta.get("text", "") or meta.get("stt_transcript", ""),
            "reference_audio": meta.get("reference_audio", ""),
            "reference_transcript": meta.get("reference_transcript", ""),
            "stt_transcript": meta.get("stt_transcript", ""),
            "has_metadata": bool(meta),
        })
    return files



def video_source_media_payload(limit: int = 150) -> list[dict[str, Any]]:
    """List saved Video Intake source media, separate from extracted audio outputs."""
    ensure_dirs()
    roots = [VIDEO_SOURCE_DIR]
    # Include old v0.62 paths if they exist, so prior saved uploads/downloads remain visible.
    for old in (VIDEO_INTAKE_DIR / "uploads", VIDEO_INTAKE_DIR / "url_imports"):
        if old.exists() and old not in roots:
            roots.append(old)
    seen: set[str] = set()
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pth in root.rglob("*"):
            if len(files) >= limit * 2:
                break
            try:
                rp = str(pth.resolve())
                if rp in seen:
                    continue
                if pth.is_file() and pth.suffix.lower() in MEDIA_EXTS and not pth.name.endswith(".preview.mp3") and pth.stat().st_size > 0:
                    seen.add(rp)
                    files.append(pth)
            except OSError:
                continue
    files.sort(key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
    payload: list[dict[str, Any]] = []
    for pth in files[:limit]:
        meta = read_output_sidecar(pth)
        try:
            rel = pth.relative_to(VIDEO_INTAKE_DIR)
            label = str(rel)
        except ValueError:
            label = pth.name
        ext = pth.suffix.lower().lstrip(".") or "media"
        payload.append({
            "name": pth.name,
            "label": label,
            "path": str(pth),
            "size": pth.stat().st_size,
            "mtime": pth.stat().st_mtime,
            "duration_seconds": audio_duration_seconds(pth),
            "ext": ext,
            "media_type": "audio" if pth.suffix.lower() in AUDIO_EXTS else "video",
            "download_url": audio_url_for(pth),
            "source_url": meta.get("source_url", ""),
            "has_metadata": bool(meta),
        })
    return payload


def write_video_source_sidecar(path: Path, meta: dict[str, Any]) -> None:
    data = dict(meta)
    data.setdefault("kind", "video-intake-source")
    data.setdefault("created_at", iso_time())
    data.setdefault("source_media", str(path))
    try:
        path.with_suffix(path.suffix + ".json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def reference_copy_path(src: Path, requested_name: str = "") -> Path:
    ensure_dirs()
    name = safe_filename(requested_name or src.name, src.name or "reference.wav")
    if Path(name).suffix.lower() not in AUDIO_EXTS:
        name = Path(name).stem + (src.suffix.lower() if src.suffix.lower() in AUDIO_EXTS else ".wav")
    target = REF_DIR / name
    if target.exists():
        target = next_versioned_path(target, always_version=False)
    return target


def save_reference_from_path(path: str, name: str = "", transcript: str = "") -> dict[str, Any]:
    src = safe_existing_path(path, [REF_DIR, OUT_DIR, PROFILE_DIR, STT_UPLOAD_DIR])
    if src.suffix.lower() not in AUDIO_EXTS:
        raise ValueError("Selected source is not an audio file.")
    target = reference_copy_path(src, name)
    if src.resolve() != target.resolve():
        shutil.copy2(src, target)
    text = str(transcript or "").strip()
    if not text:
        meta = read_output_sidecar(src)
        text = str(meta.get("stt_transcript") or meta.get("text") or "").strip()
    transcript_path = ""
    if text:
        tpath = target.with_suffix(".txt")
        tpath.write_text(text + "\n", encoding="utf-8")
        transcript_path = str(tpath)
    return {
        "path": str(target),
        "name": target.name,
        "size": target.stat().st_size,
        "duration_seconds": audio_duration_seconds(target),
        "transcript": text,
        "transcript_path": transcript_path,
    }

def video_url_slug(url: str) -> str:
    parsed = urlparse(url)
    host = safe_slug(parsed.netloc or "url", "url")
    tail = safe_slug(Path(parsed.path).stem or "video", "video")
    return f"{host}-{tail}"[:90] or "url-video"


def newest_media_file(root: Path, after_ts: float = 0.0) -> Path | None:
    candidates: list[Path] = []
    if not root.exists():
        return None
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in MEDIA_EXTS and p.stat().st_size > 0 and p.stat().st_mtime >= after_ts:
                if p.name.endswith(".part") or p.name.endswith(".ytdl"):
                    continue
                candidates.append(p)
        except OSError:
            continue
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x.stat().st_mtime, reverse=True)[0]


def parse_existing_media_path(text: str, allowed_roots: list[Path]) -> Path | None:
    for token in re.findall(r"(?:/[^\s'\"<>]+)", text or ""):
        token = token.strip().rstrip(".,;:)")
        try:
            p = Path(token).expanduser().resolve()
        except Exception:
            continue
        if p.exists() and p.is_file() and p.suffix.lower() in MEDIA_EXTS and any(inside(p, r) for r in allowed_roots):
            return p
    return None


VIDEO_DL_CANDIDATE_NAMES = (
    "video-dl", "video-dl.sh", "download", "download.sh",
    "download-video", "download-video.sh", "download_url", "download_url.sh",
    "run", "run.sh", "main.py", "app.py", "cli.py", "downloader.py",
    "download_video.py", "video_downloader.py", "yt_dlp_download.py",
)


def discover_video_dl_candidates() -> list[Path]:
    """Return executable/script candidates inside /home/user/video-dl.

    Merely finding the directory is not enough; v0.64 reported "detected"
    even when no runnable command could be inferred. Keep this conservative and
    log directory details so custom Grok-built helpers can be wired in safely.
    """
    candidates: list[Path] = []
    try:
        if VIDEO_DL_DIR.is_file() and (os.access(VIDEO_DL_DIR, os.X_OK) or VIDEO_DL_DIR.suffix == ".py"):
            candidates.append(VIDEO_DL_DIR)
        elif VIDEO_DL_DIR.is_dir():
            seen: set[Path] = set()
            for name in VIDEO_DL_CANDIDATE_NAMES:
                c = VIDEO_DL_DIR / name
                if c.exists() and c.is_file() and (os.access(c, os.X_OK) or c.suffix == ".py"):
                    rp = c.resolve()
                    if rp not in seen:
                        candidates.append(c)
                        seen.add(rp)
    except OSError:
        pass
    return candidates


def video_dl_dir_listing(limit: int = 40) -> list[str]:
    if not VIDEO_DL_DIR.exists():
        return []
    try:
        rows: list[str] = []
        for p in sorted(VIDEO_DL_DIR.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:limit]:
            marker = "/" if p.is_dir() else ("*" if os.access(p, os.X_OK) else "")
            rows.append(f"{p.name}{marker}")
        return rows
    except Exception as exc:
        return [f"<could not list directory: {exc}>"]


def command_for_video_dl_candidate(c: Path, url: str) -> list[str]:
    if c.suffix == ".py":
        return [sys.executable, str(c), url]
    return [str(c), url]


def build_video_download_commands(url: str, work_dir: Path) -> list[tuple[str, list[str], Path]]:
    commands: list[tuple[str, list[str], Path]] = []
    if VIDEO_DL_CMD:
        rendered = VIDEO_DL_CMD.replace("{url}", url).replace("{out}", str(work_dir)).replace("{output_dir}", str(work_dir))
        commands.append(("custom TTS_VIDEO_DL_CMD", shlex.split(rendered), work_dir))
    for c in discover_video_dl_candidates()[:5]:
        cwd = VIDEO_DL_DIR if VIDEO_DL_DIR.is_dir() else work_dir
        commands.append((f"/home/user/video-dl candidate {c.name}", command_for_video_dl_candidate(c, url), cwd))
    yt = shutil.which("yt-dlp")
    if yt:
        outtmpl = str(work_dir / "%(title).80s-%(id)s.%(ext)s")
        commands.append(("yt-dlp", [yt, "--no-playlist", "--no-part", "--restrict-filenames", "--merge-output-format", "mp4", "-o", outtmpl, url], work_dir))
    return commands


def video_intake_status_payload() -> dict[str, Any]:
    yt = shutil.which("yt-dlp")
    candidates = discover_video_dl_candidates()
    command_labels = []
    if VIDEO_DL_CMD:
        command_labels.append("TTS_VIDEO_DL_CMD")
    command_labels.extend(str(p) for p in candidates)
    if yt:
        command_labels.append(yt)
    return {
        "ready": bool(command_labels),
        "video_dl_dir": str(VIDEO_DL_DIR),
        "video_dl_dir_exists": VIDEO_DL_DIR.exists(),
        "video_dl_candidates": [p.name for p in candidates],
        "video_dl_dir_listing": video_dl_dir_listing(),
        "yt_dlp": yt or "",
        "custom_command": bool(VIDEO_DL_CMD),
        "commands": command_labels,
    }


def ensure_resemble_compat_wrapper() -> dict[str, Any]:
    """Write a small launcher/wrapper for Resemble Enhance torch/torchaudio Path handling."""
    try:
        RESEMBLE_ROOT.mkdir(parents=True, exist_ok=True)
        wrapper_py = '#!/usr/bin/env python3\n"""Direct Resemble Enhance runner for TTS Lab Web UI.\n\nThis keeps the installed package unmodified while avoiding fragile behavior in\nsome packaged CLI builds. It processes .wav files from an input directory,\navoids torchaudio audio-file I/O for load/save because some local torch/torchaudio\nstacks segfault there, prints step-by-step diagnostics, and exits non-zero if no\noutput file is written.\n"""\nfrom __future__ import annotations\n\nimport argparse\nimport random\nimport time\nimport traceback\nimport wave\nfrom pathlib import Path\n\n\ndef _log(message: str) -> None:\n    print(message, flush=True)\n\n\ndef _load_wav_stdlib(path: Path):\n    """Load mono float32 audio from a PCM WAV without torchaudio file I/O."""\n    import numpy as np\n    import torch\n\n    with wave.open(str(path), "rb") as wf:\n        channels = wf.getnchannels()\n        sampwidth = wf.getsampwidth()\n        sr = wf.getframerate()\n        frames = wf.getnframes()\n        comptype = wf.getcomptype()\n        raw = wf.readframes(frames)\n\n    if comptype != "NONE":\n        raise RuntimeError(f"Unsupported compressed WAV type {comptype!r}; stage input through ffmpeg as PCM WAV.")\n    if channels < 1:\n        raise RuntimeError("WAV has no audio channels.")\n\n    if sampwidth == 1:\n        arr = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0\n    elif sampwidth == 2:\n        arr = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0\n    elif sampwidth == 3:\n        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)\n        vals = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))\n        vals = np.where(vals & 0x800000, vals - 0x1000000, vals)\n        arr = vals.astype(np.float32) / 8388608.0\n    elif sampwidth == 4:\n        arr = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0\n    else:\n        raise RuntimeError(f"Unsupported WAV sample width: {sampwidth} bytes")\n\n    if arr.size % channels != 0:\n        raise RuntimeError(f"WAV sample count {arr.size} is not divisible by channel count {channels}")\n    arr = arr.reshape(-1, channels)\n    mono = arr.mean(axis=1).astype(np.float32, copy=False)\n    return torch.from_numpy(mono.copy()), int(sr), {"channels": channels, "sample_width": sampwidth, "frames": frames}\n\n\ndef _save_wav_stdlib(path: Path, audio, sr: int) -> None:\n    """Save mono float audio as PCM16 WAV without torchaudio file I/O."""\n    import numpy as np\n    import torch\n\n    if isinstance(audio, torch.Tensor):\n        arr = audio.detach().float().cpu().numpy()\n    else:\n        arr = np.asarray(audio, dtype=np.float32)\n    arr = np.squeeze(arr)\n    if arr.ndim != 1:\n        arr = arr.reshape(-1)\n    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)\n    arr = np.clip(arr, -1.0, 1.0)\n    pcm = (arr * 32767.0).astype("<i2")\n    path.parent.mkdir(parents=True, exist_ok=True)\n    with wave.open(str(path), "wb") as wf:\n        wf.setnchannels(1)\n        wf.setsampwidth(2)\n        wf.setframerate(int(sr))\n        wf.writeframes(pcm.tobytes())\n\n\ndef main() -> int:\n    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)\n    parser.add_argument("in_dir", type=Path, help="Path to input audio folder")\n    parser.add_argument("out_dir", type=Path, help="Output folder")\n    parser.add_argument("--run_dir", type=Path, default=None, help="Path to the enhancer run folder, if None, use the default model")\n    parser.add_argument("--suffix", type=str, default=".wav", help="Audio file suffix")\n    parser.add_argument("--device", type=str, default="cuda", help="Device to use: cuda, cpu, or auto")\n    parser.add_argument("--denoise_only", action="store_true", help="Only apply denoising without enhancement")\n    parser.add_argument("--lambd", type=float, default=1.0, help="Denoise strength for enhancement (0.0 to 1.0)")\n    parser.add_argument("--tau", type=float, default=0.5, help="CFM prior temperature (0.0 to 1.0)")\n    parser.add_argument("--solver", type=str, default="midpoint", choices=["midpoint", "rk4", "euler"], help="Numerical solver to use")\n    parser.add_argument("--nfe", type=int, default=64, help="Number of function evaluations")\n    parser.add_argument("--parallel_mode", action="store_true", help="Shuffle the audio paths and skip existing outputs")\n    args = parser.parse_args()\n\n    try:\n        import torch\n        from resemble_enhance.enhancer.inference import denoise, enhance\n    except Exception:\n        _log("ERROR: Could not import Resemble Enhance runtime dependencies.")\n        traceback.print_exc()\n        return 1\n\n    device = args.device.lower().strip()\n    if device == "auto":\n        device = "cuda" if torch.cuda.is_available() else "cpu"\n    if device == "cuda" and not torch.cuda.is_available():\n        _log("CUDA is not available but --device is cuda; using CPU instead.")\n        device = "cpu"\n    if device not in {"cuda", "cpu"}:\n        _log(f"Unknown device {args.device!r}; use cuda, cpu, or auto.")\n        return 2\n\n    _log("TTS Web UI Resemble direct runner active.")\n    _log("This runner avoids packaged CLI pathlib/torchaudio issues and avoids torchaudio file load/save SIGSEGVs.")\n    _log("Audio I/O backend: Python wave + numpy PCM loader/saver. Model inference still uses the installed Resemble package.")\n    _log(f"Input directory: {args.in_dir}")\n    _log(f"Output directory: {args.out_dir}")\n    _log(f"Mode: {\'denoise_only\' if args.denoise_only else \'enhance\'}")\n    _log(f"Device: {device}")\n    _log(f"Suffix: {args.suffix}")\n    if not args.in_dir.exists():\n        _log(f"ERROR: input directory does not exist: {args.in_dir}")\n        return 3\n    args.out_dir.mkdir(parents=True, exist_ok=True)\n\n    paths = sorted(args.in_dir.glob(f"**/*{args.suffix}"))\n    if args.parallel_mode:\n        random.shuffle(paths)\n    _log(f"Input files discovered: {len(paths)}")\n    if len(paths) == 0:\n        _log(f"No {args.suffix} files found in the following path: {args.in_dir}")\n        return 4\n\n    start_time = time.perf_counter()\n    written = []\n    for idx, path in enumerate(paths, start=1):\n        out_path = args.out_dir / path.relative_to(args.in_dir)\n        if args.parallel_mode and out_path.exists():\n            _log(f"[{idx}/{len(paths)}] Skipping existing output: {out_path}")\n            written.append(out_path)\n            continue\n        try:\n            _log(f"[{idx}/{len(paths)}] Loading audio without torchaudio file I/O: {path}")\n            dwav, sr, info = _load_wav_stdlib(path)\n            _log(f"[{idx}/{len(paths)}] Loaded tensor shape={tuple(dwav.shape)} sample_rate={sr} channels={info[\'channels\']} sample_width={info[\'sample_width\']} frames={info[\'frames\']}")\n            if args.denoise_only:\n                _log(f"[{idx}/{len(paths)}] Running denoise...")\n                hwav, sr = denoise(dwav=dwav, sr=sr, device=device, run_dir=args.run_dir)\n            else:\n                _log(f"[{idx}/{len(paths)}] Running enhance solver={args.solver} nfe={args.nfe} lambd={args.lambd} tau={args.tau}...")\n                hwav, sr = enhance(dwav=dwav, sr=sr, device=device, nfe=args.nfe, solver=args.solver, lambd=args.lambd, tau=args.tau, run_dir=args.run_dir)\n            try:\n                shape = tuple(hwav.shape)\n            except Exception:\n                shape = ("unknown",)\n            _log(f"[{idx}/{len(paths)}] Model returned shape={shape} sample_rate={sr}")\n            out_path.parent.mkdir(parents=True, exist_ok=True)\n            _log(f"[{idx}/{len(paths)}] Saving output without torchaudio file I/O: {out_path}")\n            _save_wav_stdlib(out_path, hwav, sr)\n            if not out_path.exists() or out_path.stat().st_size <= 0:\n                _log(f"ERROR: save completed but output file is missing or empty: {out_path}")\n                return 5\n            _log(f"[{idx}/{len(paths)}] Output written: {out_path} ({out_path.stat().st_size} bytes)")\n            written.append(out_path)\n        except Exception:\n            _log(f"ERROR while processing {path}")\n            traceback.print_exc()\n            return 1\n\n    elapsed_time = time.perf_counter() - start_time\n    _log(f"Enhancement done. {len(written)} files written in {elapsed_time:.2f}s")\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
        launcher = '''#!/usr/bin/env bash
set -euo pipefail
LAB="${TTS_LAB:-/home/user/tts-lab}"
ROOT="${TTS_RESEMBLE_ROOT:-$LAB/engines/resemble-enhance}"
ENV_NAME="${TTS_RESEMBLE_CONDA_ENV:-tts-resemble-enhance}"
WRAPPER="${TTS_RESEMBLE_COMPAT_WRAPPER:-$ROOT/resemble_enhance_webui_wrapper.py}"

if [[ -n "${TTS_RESEMBLE_PYTHON:-}" && -x "${TTS_RESEMBLE_PYTHON:-}" ]]; then
  PY="$TTS_RESEMBLE_PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif [[ -x "$HOME/miniconda3/envs/$ENV_NAME/bin/python" ]]; then
  PY="$HOME/miniconda3/envs/$ENV_NAME/bin/python"
elif [[ -x "$HOME/anaconda3/envs/$ENV_NAME/bin/python" ]]; then
  PY="$HOME/anaconda3/envs/$ENV_NAME/bin/python"
else
  echo "ERROR: Resemble Enhance compatibility launcher could not find an isolated env Python." >&2
  echo "Checked: $ROOT/.venv/bin/python, $HOME/miniconda3/envs/$ENV_NAME/bin/python, $HOME/anaconda3/envs/$ENV_NAME/bin/python" >&2
  exit 127
fi

if [[ ! -f "$WRAPPER" ]]; then
  echo "ERROR: Resemble Enhance compatibility wrapper not found: $WRAPPER" >&2
  exit 127
fi

ENV_BIN="$(dirname "$PY")"
# Put the isolated Resemble environment first so subprocess calls such as
# `git lfs pull` can find env-local tools like git-lfs.
export PATH="$ENV_BIN:${PATH:-}"
exec "$PY" "$WRAPPER" "$@"
'''
        RESEMBLE_COMPAT_WRAPPER.write_text(wrapper_py, encoding="utf-8")
        RESEMBLE_COMPAT_LAUNCHER.write_text(launcher, encoding="utf-8")
        os.chmod(RESEMBLE_COMPAT_WRAPPER, 0o755)
        os.chmod(RESEMBLE_COMPAT_LAUNCHER, 0o755)
        return {"ok": True, "launcher": str(RESEMBLE_COMPAT_LAUNCHER), "wrapper": str(RESEMBLE_COMPAT_WRAPPER)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "launcher": str(RESEMBLE_COMPAT_LAUNCHER), "wrapper": str(RESEMBLE_COMPAT_WRAPPER)}


def conda_exe_path() -> Path | None:
    candidates = [
        os.environ.get("CONDA_EXE", "").strip(),
        str(Path.home() / "miniconda3" / "bin" / "conda"),
        str(Path.home() / "anaconda3" / "bin" / "conda"),
        shutil.which("conda") or "",
    ]
    for raw in candidates:
        if not raw:
            continue
        p = Path(raw).expanduser()
        if p.exists() and os.access(p, os.X_OK):
            return p
    return None



def resemble_env_name() -> str:
    return os.environ.get("TTS_RESEMBLE_CONDA_ENV", "tts-resemble-enhance")


def resemble_env_python_candidates() -> list[Path]:
    env_name = resemble_env_name()
    out: list[Path] = []
    override = os.environ.get("TTS_RESEMBLE_PYTHON", "").strip()
    if override:
        out.append(Path(override).expanduser())
    out.extend([
        RESEMBLE_ROOT / ".venv" / "bin" / "python",
        Path.home() / "miniconda3" / "envs" / env_name / "bin" / "python",
        Path.home() / "anaconda3" / "envs" / env_name / "bin" / "python",
    ])
    return out


def resemble_env_python_path() -> Path | None:
    for p in resemble_env_python_candidates():
        if p.exists() and os.access(p, os.X_OK):
            return p
    return None


def resemble_env_bin_path() -> Path | None:
    py = resemble_env_python_path()
    return py.parent if py else None


def resemble_runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    env_bin = resemble_env_bin_path()
    if env_bin:
        env["PATH"] = str(env_bin) + os.pathsep + env.get("PATH", "")
    return env


def _run_short_command(cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 20) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout, env=env or os.environ.copy())
        return {"ok": proc.returncode == 0, "returncode": proc.returncode, "output": (proc.stdout or "").strip()[-3000:]}
    except FileNotFoundError as exc:
        return {"ok": False, "returncode": 127, "output": str(exc)}
    except Exception as exc:
        return {"ok": False, "returncode": -1, "output": str(exc)}


def resemble_git_lfs_status() -> dict[str, Any]:
    """Detect Git LFS as Resemble sees it from its isolated runtime PATH."""
    env = resemble_runtime_env()
    env_bin = resemble_env_bin_path()
    git = shutil.which("git", path=env.get("PATH")) or ""
    git_lfs_binary = shutil.which("git-lfs", path=env.get("PATH")) or ""
    git_version = _run_short_command([git or "git", "--version"], env=env) if (git or shutil.which("git")) else {"ok": False, "output": "git not found"}
    git_lfs_subcommand = _run_short_command([git or "git", "lfs", "version"], env=env) if (git or shutil.which("git")) else {"ok": False, "output": "git not found"}
    git_lfs_direct = _run_short_command([git_lfs_binary or "git-lfs", "--version"], env=env) if (git_lfs_binary or shutil.which("git-lfs")) else {"ok": False, "output": "git-lfs not found"}
    available = bool(git_lfs_subcommand.get("ok") or git_lfs_direct.get("ok"))
    return {
        "available": available,
        "env_bin": str(env_bin) if env_bin else "",
        "path_prefix_applied": bool(env_bin),
        "git": git,
        "git_lfs_binary": git_lfs_binary,
        "git_version": git_version,
        "git_lfs_subcommand": git_lfs_subcommand,
        "git_lfs_direct": git_lfs_direct,
        "message": "Git LFS available for Resemble model downloads." if available else "Git LFS is not available from the isolated Resemble runtime PATH. Resemble model download may fail with git: 'lfs' is not a git command.",
    }

def resemble_command_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if RESEMBLE_CMD:
        try:
            parts = shlex.split(RESEMBLE_CMD)
        except Exception:
            parts = []
        candidates.append({"kind": "manual", "label": "TTS_RESEMBLE_CMD", "command": parts, "configured": True, "exists": bool(parts)})
    wrapper_status = ensure_resemble_compat_wrapper()
    env_name = resemble_env_name()
    wrapper_python = resemble_env_python_path()
    candidates.append({"kind": "webui-wrapper", "label": "Web UI compatibility wrapper", "path": str(RESEMBLE_COMPAT_LAUNCHER), "python": str(wrapper_python) if wrapper_python else "", "wrapper": wrapper_status, "command": [str(RESEMBLE_COMPAT_LAUNCHER)], "exists": RESEMBLE_COMPAT_LAUNCHER.exists() and os.access(RESEMBLE_COMPAT_LAUNCHER, os.X_OK) and bool(wrapper_python)})
    venv_bin = RESEMBLE_ROOT / ".venv" / "bin" / "resemble-enhance"
    candidates.append({"kind": "venv", "label": "dedicated venv direct CLI", "path": str(venv_bin), "command": [str(venv_bin)], "exists": venv_bin.exists() and os.access(venv_bin, os.X_OK)})
    conda_bin = Path.home() / "miniconda3" / "envs" / env_name / "bin" / "resemble-enhance"
    candidates.append({"kind": "conda-path", "label": "conda env direct CLI", "path": str(conda_bin), "command": [str(conda_bin)], "exists": conda_bin.exists() and os.access(conda_bin, os.X_OK)})
    conda = conda_exe_path()
    if conda:
        conda_env_exists = conda_bin.exists() and os.access(conda_bin, os.X_OK)
        candidates.append({"kind": "conda-run", "label": "conda run tts-resemble-enhance", "path": str(conda), "command": [str(conda), "run", "-n", env_name, "resemble-enhance"], "exists": conda_env_exists})
    return candidates


def resemble_best_command() -> list[str]:
    for c in resemble_command_candidates():
        if c.get("exists") and c.get("command"):
            return list(c["command"])
    return []


def resemble_status_payload() -> dict[str, Any]:
    conda = conda_exe_path()
    candidates = resemble_command_candidates()
    ready = any(c.get("exists") for c in candidates)
    return {
        "ready": ready,
        "root": str(RESEMBLE_ROOT),
        "output_dir": str(RESEMBLE_OUTPUT_DIR),
        "installer": str(RESEMBLE_INSTALLER),
        "installer_exists": RESEMBLE_INSTALLER.exists() and os.access(RESEMBLE_INSTALLER, os.X_OK),
        "install_mode_default": "conda" if conda else "venv",
        "conda": str(conda) if conda else "",
        "manual_command_configured": bool(RESEMBLE_CMD),
        "candidates": candidates,
        "best_command": resemble_best_command(),
        "compat_launcher": str(RESEMBLE_COMPAT_LAUNCHER),
        "compat_wrapper": str(RESEMBLE_COMPAT_WRAPPER),
        "env_python": str(resemble_env_python_path() or ""),
        "env_bin": str(resemble_env_bin_path() or ""),
        "git_lfs": resemble_git_lfs_status(),
        "notes": "Resemble Enhance is isolated from the main Web UI environment. The Web UI prefers its direct runner, prepends the isolated env bin directory to PATH, and checks Git LFS because Resemble uses it to download model files.",
    }


def whisper_python_path() -> Path:
    override = os.environ.get("TTS_WHISPER_PYTHON", "").strip()
    if override:
        return Path(override)
    return WHISPER_PYTHON



def read_hf_token() -> str:
    try:
        return HF_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def masked_token(token: str) -> str:
    token = str(token or "").strip()
    if not token:
        return ""
    if len(token) <= 12:
        return token[:3] + "..."
    return token[:6] + "..." + token[-4:]


def hf_token_status_payload() -> dict[str, Any]:
    token = read_hf_token()
    return {"configured": bool(token), "masked": masked_token(token), "path": str(HF_TOKEN_FILE)}


def save_hf_token(token: str) -> dict[str, Any]:
    token = str(token or "").strip()
    if not token:
        raise ValueError("Paste a read-only Hugging Face token first.")
    if not token.startswith("hf_"):
        raise ValueError("That does not look like a Hugging Face token. It should usually start with hf_.")
    ensure_dirs()
    HF_TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    try:
        HF_TOKEN_FILE.chmod(0o600)
    except Exception:
        pass
    return hf_token_status_payload()


def forget_hf_token() -> dict[str, Any]:
    try:
        HF_TOKEN_FILE.unlink()
    except FileNotFoundError:
        pass
    return hf_token_status_payload()


def whisper_nvidia_lib_dirs() -> list[str]:
    roots: list[str] = []
    candidates = [
        whisper_python_path().parent.parent / "lib" / "python3.11" / "site-packages" / "nvidia",
        Path.home() / "miniconda3" / "envs" / "tts-whisper" / "lib" / "python3.11" / "site-packages" / "nvidia",
    ]
    for base in candidates:
        if base.exists():
            for d in base.rglob("lib"):
                if d.is_dir():
                    roots.append(str(d))
    # preserve order while de-duping
    seen: set[str] = set()
    out: list[str] = []
    for r in roots:
        if r not in seen:
            seen.add(r); out.append(r)
    return out


def hf_env() -> dict[str, str]:
    env = os.environ.copy()
    token = read_hf_token()
    if token and not env.get("HF_TOKEN"):
        env["HF_TOKEN"] = token
    cuda_libs = whisper_nvidia_lib_dirs()
    if cuda_libs:
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join(cuda_libs + ([existing] if existing else []))
    return env


def test_hf_token() -> dict[str, Any]:
    token = read_hf_token()
    if not token:
        return {"ok": False, "message": "No Hugging Face token is saved yet."}
    py = whisper_python_path()
    if not py.exists():
        return {"ok": False, "message": "tts-whisper is not installed yet, so the token cannot be tested from this environment."}
    code = """
from huggingface_hub import HfApi
import os
api = HfApi(token=os.environ.get('HF_TOKEN'))
info = api.whoami()
name = info.get('name') or info.get('fullname') or info.get('email') or 'token accepted'
print(name)
""".strip()
    try:
        proc = subprocess.run([str(py), "-c", code], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30, env=hf_env())
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    out = (proc.stdout or "").strip()
    if proc.returncode == 0:
        return {"ok": True, "message": "Hugging Face token accepted: " + (out or masked_token(token))}
    return {"ok": False, "message": out[-1000:] or f"Token test failed with exit code {proc.returncode}."}

def whisper_status_payload() -> dict[str, Any]:
    py = whisper_python_path()
    install_cmd = str(LAB / "install-whisper.sh")
    data = {"python": str(py), "helper": str(WHISPER_HELPER), "ready": False, "install_command": install_cmd, "error": "", "hf_token": hf_token_status_payload()}
    if not WHISPER_HELPER.exists():
        data["error"] = "Whisper helper script is missing from the web UI install."
        return data
    if not py.exists():
        data["error"] = "tts-whisper conda environment is not installed yet."
        return data
    try:
        proc = subprocess.run([str(py), "-c", "import faster_whisper; print('ok')"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
        if proc.returncode == 0:
            data["ready"] = True
        else:
            data["error"] = proc.stdout.strip()[-500:]
    except Exception as exc:
        data["error"] = str(exc)
    return data


def test_whisper_gpu_support() -> dict[str, Any]:
    """Run a real tiny CUDA transcription path, not just model construction.

    Loading the model alone can succeed even when the first encode/transcribe call
    fails with missing libcublas/cuDNN. This writes a short local WAV and invokes
    the same helper with device=cuda/float16 so the test exercises the path that
    real transcription uses.
    """
    status = whisper_status_payload()
    if not status.get("ready"):
        return {"ok": False, "message": "Faster-Whisper is not ready: " + str(status.get("error", ""))}
    py = whisper_python_path()
    ensure_dirs()
    test_wav = STT_UPLOAD_DIR / "_whisper_gpu_test_silence.wav"
    try:
        with wave.open(str(test_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\0\0" * 16000)
    except Exception as exc:
        return {"ok": False, "message": "Could not create GPU test WAV: " + str(exc)}
    cmd = [str(py), str(WHISPER_HELPER), str(test_wav), "--model", "tiny", "--device", "cuda", "--compute-type", "float16", "--language", "en"]
    try:
        proc = subprocess.run(cmd, cwd=str(LAB), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180, env=hf_env())
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    raw = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    if proc.returncode != 0:
        return {"ok": False, "message": raw[-3000:] or f"GPU test failed with exit code {proc.returncode}."}
    try:
        data = json.loads(proc.stdout)
    except Exception:
        return {"ok": False, "message": "GPU helper returned non-JSON output: " + raw[-2000:]}
    if data.get("device") == "cuda" and str(data.get("compute_type", "")).lower() == "float16":
        return {"ok": True, "message": "Real CUDA transcription path passed: device=cuda, compute=float16."}
    return {"ok": False, "message": "GPU test ran but did not report cuda/float16. Result: " + json.dumps(data)[:1000]}


def fmt_seconds(value: Any) -> str:
    try:
        if value is None:
            return "unknown"
        sec = float(value)
        if sec < 60:
            return f"{sec:.1f}s"
        return f"{int(sec//60)}:{int(round(sec%60)):02d}"
    except Exception:
        return "unknown"


def stt_sources_payload() -> list[dict[str, Any]]:
    ensure_dirs()
    sources: list[dict[str, Any]] = []
    for p in profiles_payload():
        if p.get("ok"):
            sources.append({"type":"profile", "label":f"Profile audio: {p.get('name','')} ({fmt_seconds(p.get('duration_seconds'))})", "path":p.get("audio_path", ""), "transcript":p.get("transcript", ""), "transcript_label":"saved profile transcript"})
    for r in loose_refs_payload():
        sources.append({"type":"reference", "label":f"Loose reference audio: {r.get('name','')} ({fmt_seconds(r.get('duration_seconds'))})", "path":r.get("path", ""), "transcript":r.get("transcript", ""), "transcript_label":"saved loose-reference transcript"})
    for o in outputs_payload()[:60]:
        sources.append({"type":"output", "label":f"Generated output: {o.get('name','')} ({fmt_seconds(o.get('duration_seconds'))})", "path":o.get("path", ""), "transcript":o.get("stt_transcript") or o.get("text", ""), "transcript_label":"saved output text/transcript"})
    for p in sorted(STT_UPLOAD_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            sources.append({"type":"upload", "label":f"STT upload: {p.name} ({fmt_seconds(audio_duration_seconds(p))})", "path":str(p), "transcript":read_text_file_if_exists(companion_transcript(p)), "transcript_label":"saved transcript beside uploaded audio"})
    return [src for src in sources if src.get("path")]




def audio_lab_sources_payload() -> list[dict[str, Any]]:
    """Audio sources usable in Audio Lab. Keep labels friendly and paths explicit."""
    sources: list[dict[str, Any]] = []
    for src in stt_sources_payload():
        label = str(src.get("label") or src.get("path") or "audio")
        sources.append({"label": label, "path": src.get("path", ""), "duration_seconds": audio_duration_seconds(Path(str(src.get("path", "")))) if src.get("path") else None})
    for src in video_source_media_payload()[:60]:
        if src.get("media_type") == "audio" and src.get("path"):
            sources.append({"label": f"Video Intake archived audio source: {src.get('label') or src.get('name')} ({fmt_seconds(src.get('duration_seconds'))})", "path": src.get("path", ""), "duration_seconds": src.get("duration_seconds")})
    for p in sorted(AUDIO_LAB_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.endswith(".preview.mp3"):
            continue
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            sources.append({"label": f"Audio Lab output: {p.name} ({fmt_seconds(audio_duration_seconds(p))})", "path": str(p), "duration_seconds": audio_duration_seconds(p)})
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in sources:
        path = str(item.get("path") or "")
        if path and path not in seen:
            seen.add(path)
            out.append(item)
    return out

def resemble_sources_payload() -> list[dict[str, Any]]:
    """Audio sources usable in the isolated Resemble Enhance test bench."""
    ensure_dirs()
    sources: list[dict[str, Any]] = []
    for src in audio_lab_sources_payload():
        path = str(src.get("path") or "")
        if path:
            sources.append({
                "label": str(src.get("label") or Path(path).name),
                "path": path,
                "duration_seconds": src.get("duration_seconds"),
            })
    for p in sorted(RESEMBLE_INPUT_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            sources.append({
                "label": f"Resemble upload: {p.name} ({fmt_seconds(audio_duration_seconds(p))})",
                "path": str(p),
                "duration_seconds": audio_duration_seconds(p),
            })
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in sources:
        path = str(item.get("path") or "")
        if path and path not in seen:
            seen.add(path)
            out.append(item)
    return out


def resemble_output_path(
    src: Path,
    fmt: str,
    custom_text: str = "",
    custom_mode: str = "none",
    date_mode: str = "none",
    version_mode: str = "collision",
    function_mode: str = "none",
    filename_template: str = "",
    function_label: str = "enhanced",
) -> Path:
    return named_output_path(
        RESEMBLE_OUTPUT_DIR,
        src,
        fmt,
        custom_text=custom_text,
        custom_mode=custom_mode,
        date_mode=date_mode,
        version_mode=version_mode,
        function_mode=function_mode,
        filename_template=filename_template,
        function_label=function_label,
        fallback_base="resemble-audio",
    )


def short_dir_listing(path: Path, limit: int = 80) -> str:
    try:
        rows: list[str] = []
        for item in sorted(path.rglob("*"), key=lambda x: str(x).lower())[:limit]:
            rel = item.relative_to(path)
            marker = "/" if item.is_dir() else f" ({item.stat().st_size} bytes)"
            rows.append(str(rel) + marker)
        return "\n".join(rows) if rows else "<empty>"
    except Exception as exc:
        return f"<could not list {path}: {exc}>"



def audio_lab_output_format(src: Path, fmt_choice: str) -> str:
    """Resolve Audio Lab output format choice to a file extension without the dot."""
    fmt_choice = (fmt_choice or "unchanged").lower().strip().lstrip(".")
    if fmt_choice in {"wav", "mp3", "flac"}:
        return fmt_choice
    src_ext = src.suffix.lower().lstrip(".")
    return src_ext if src_ext in {"wav", "mp3", "flac", "ogg", "m4a", "aac", "opus"} else "wav"


def next_versioned_path(base_path: Path, *, always_version: bool = False) -> Path:
    """Return base_path, or base-vN.ext. If always_version, start with -v1."""
    if not always_version and not base_path.exists():
        return base_path
    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent
    n = 1
    while True:
        candidate = parent / f"{stem}-v{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def filename_token_values(src: Path, fmt: str, custom_text: str, function_label: str) -> dict[str, str]:
    t = time.localtime()
    source = safe_slug(src.stem, "source")
    custom = safe_slug(custom_text, "") if custom_text.strip() else ""
    function = safe_slug(function_label, "") if function_label.strip() else ""
    return {
        "source": source,
        "custom": custom,
        "function": function,
        "ext": fmt,
        ".ext": f".{fmt}",
        "YYYYMMDD": time.strftime("%Y%m%d", t),
        "YYYY-MM-DD": time.strftime("%Y-%m-%d", t),
        "year": time.strftime("%Y", t),
        "month": time.strftime("%m", t),
        "day": time.strftime("%d", t),
        "weekday": time.strftime("%A", t),
        "time24": time.strftime("%H%M", t),
        "time24hour": time.strftime("%H%M", t),
        "time12": time.strftime("%I%M%p", t).lstrip("0"),
        "time-am-pm": time.strftime("%I%M%p", t).lstrip("0"),
        "timestamp": time.strftime("%Y%m%d_%H%M%S", t),
    }


def render_filename_template(template: str, tokens: dict[str, str], version: str = "") -> str:
    template = str(template or "[source][version][.ext]").strip() or "[source][version][.ext]"
    values = dict(tokens)
    values["version"] = version
    # Replace longer token names first so [.ext] is handled before [ext].
    for key in sorted(values.keys(), key=len, reverse=True):
        template = template.replace(f"[{key}]", values[key])
    return template


def normalize_rendered_filename(rendered: str, fmt: str, fallback_base: str) -> str:
    rendered = re.sub(r"-{2,}", "-", rendered)
    rendered = re.sub(r"_{2,}", "_", rendered)
    rendered = re.sub(r"\s+", " ", rendered).strip(" ._-\t\r\n")
    if not rendered.lower().endswith(f".{fmt.lower()}"):
        rendered = f"{rendered}.{fmt}"
    return safe_filename(rendered, f"{fallback_base}.{fmt}")


def output_path_from_template(
    out_dir: Path,
    src: Path,
    fmt: str,
    template: str,
    custom_text: str = "",
    version_mode: str = "collision",
    function_label: str = "",
    fallback_base: str = "audio",
) -> Path:
    ensure_dirs()
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = (fmt or "wav").lower().strip().lstrip(".") or "wav"
    tokens = filename_token_values(src, fmt, custom_text, function_label)
    version_mode = (version_mode or "collision").lower().strip()

    def candidate(version: str = "") -> Path:
        rendered = render_filename_template(template, tokens, version=version)
        return out_dir / normalize_rendered_filename(rendered, fmt, fallback_base)

    if version_mode == "always":
        n = 1
        while True:
            p = candidate(f"-v{n}")
            if not p.exists():
                return p
            n += 1
    first = candidate("")
    if version_mode == "collision":
        if not first.exists():
            return first
        n = 1
        while True:
            p = candidate(f"-v{n}")
            if not p.exists():
                return p
            n += 1
    if first.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return out_dir / f"{safe_slug(first.stem, fallback_base)}-{stamp}-{uuid.uuid4().hex[:6]}{first.suffix}"
    return first


def legacy_dropdown_template(
    custom_text: str = "",
    custom_mode: str = "none",
    date_mode: str = "none",
    function_mode: str = "none",
) -> str:
    base = "[source]"
    custom_mode = (custom_mode or "none").lower().strip()
    if custom_mode == "prefix":
        base = "[custom]-" + base
    elif custom_mode == "suffix":
        base = base + "-[custom]"
    elif custom_mode == "replace":
        base = "[custom]"
    function_mode = (function_mode or "none").lower().strip()
    if function_mode == "prefix":
        base = "[function]-" + base
    elif function_mode == "suffix":
        base = base + "-[function]"
    date_mode = (date_mode or "none").lower().strip()
    if date_mode == "prefix":
        base = "[YYYYMMDD]-" + base
    elif date_mode == "suffix":
        base = base + "-[YYYYMMDD]"
    return base + "[version][.ext]"


def named_output_path(
    out_dir: Path,
    src: Path,
    fmt: str,
    custom_text: str = "",
    custom_mode: str = "none",
    date_mode: str = "none",
    version_mode: str = "collision",
    function_mode: str = "none",
    filename_template: str = "",
    function_label: str = "",
    fallback_base: str = "audio",
) -> Path:
    template = filename_template or legacy_dropdown_template(custom_text, custom_mode, date_mode, function_mode)
    return output_path_from_template(
        out_dir,
        src,
        fmt,
        template=template,
        custom_text=custom_text,
        version_mode=version_mode,
        function_label=function_label,
        fallback_base=fallback_base,
    )


def audio_lab_output_path(
    src: Path,
    fmt: str,
    custom_text: str = "",
    custom_mode: str = "none",
    date_mode: str = "none",
    version_mode: str = "collision",
    function_mode: str = "none",
    filename_template: str = "",
) -> Path:
    return named_output_path(
        AUDIO_LAB_DIR,
        src,
        fmt,
        custom_text=custom_text,
        custom_mode=custom_mode,
        date_mode=date_mode,
        version_mode=version_mode,
        function_mode=function_mode,
        filename_template=filename_template,
        function_label="clean",
        fallback_base="audio-lab",
    )


def video_intake_output_format(fmt_choice: str) -> str:
    fmt_choice = (fmt_choice or "wav").lower().strip().lstrip(".")
    return fmt_choice if fmt_choice in {"wav", "mp3", "flac"} else "wav"


def video_intake_output_path(
    src: Path,
    fmt: str,
    custom_text: str = "",
    custom_mode: str = "none",
    date_mode: str = "none",
    version_mode: str = "collision",
    function_mode: str = "none",
    filename_template: str = "",
) -> Path:
    return named_output_path(
        VIDEO_EXTRACT_DIR,
        src,
        fmt,
        custom_text=custom_text,
        custom_mode=custom_mode,
        date_mode=date_mode,
        version_mode=version_mode,
        function_mode=function_mode,
        filename_template=filename_template,
        function_label="extracted",
        fallback_base="video-audio",
    )

def audio_lab_waveform_path(audio_path: Path, suffix: str = "waveform") -> Path:
    ensure_dirs()
    safe = safe_slug(audio_path.stem)[:80] or "audio"
    return AUDIO_LAB_DIR / f"{safe}_{suffix}_{uuid.uuid5(uuid.NAMESPACE_URL, str(audio_path.resolve())).hex[:8]}.svg"

def create_waveform_svg(audio_path: Path, svg_path: Path, width: int = 900, height: int = 160, max_points: int = 900) -> bool:
    """Create a lightweight before/after waveform SVG using ffmpeg-decoded mono PCM."""
    try:
        if not audio_path.exists() or audio_path.suffix.lower() not in AUDIO_EXTS:
            return False
        cmd = [
            "ffmpeg", "-v", "error", "-i", str(audio_path),
            "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
        if proc.returncode != 0 or not proc.stdout:
            return False
        samples = array.array("h")
        samples.frombytes(proc.stdout)
        if sys.byteorder != "little":
            samples.byteswap()
        n = len(samples)
        if n <= 0:
            return False
        points = min(max_points, width, n)
        bucket = max(1, math.ceil(n / points))
        vals = []
        for i in range(0, n, bucket):
            chunk = samples[i:i+bucket]
            if not chunk:
                continue
            vals.append(max(abs(int(x)) for x in chunk) / 32768.0)
        if not vals:
            return False
        mid = height / 2
        scale = height * 0.44
        step = width / max(1, len(vals)-1)
        line_markup = []
        for idx, v in enumerate(vals):
            x = idx * step
            y1 = mid - v * scale
            y2 = mid + v * scale
            line_markup.append(f'<line x1="{x:.2f}" y1="{y1:.2f}" x2="{x:.2f}" y2="{y2:.2f}" />')
        lines = "".join(line_markup)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-label="Audio waveform">\n'
            f'  <rect width="100%" height="100%" fill="#0d1016"/>\n'
            f'  <line x1="0" y1="{mid:.2f}" x2="{width}" y2="{mid:.2f}" stroke="#39465a" stroke-width="1"/>\n'
            f'  <g stroke="#7fb7ff" stroke-width="1" opacity="0.92">{lines}</g>\n'
            f'</svg>\n'
        )
        svg_path.write_text(svg, encoding="utf-8")
        return True
    except Exception:
        return False

def transcribe_with_faster_whisper(path: str, model: str = "base", language: str = "auto", device: str = "auto") -> dict[str, Any]:
    src = safe_existing_path(path, [REF_DIR, OUT_DIR, PROFILE_DIR, STT_UPLOAD_DIR])
    if src.suffix.lower() not in AUDIO_EXTS:
        raise ValueError("Selected STT source is not an audio file.")
    status = whisper_status_payload()
    if not status.get("ready"):
        raise RuntimeError("Faster-Whisper is not ready. " + str(status.get("error", "")) + " Run: " + str(status.get("install_command", "")))
    model = str(model or "base").strip().lower()
    if model not in {"tiny", "base", "small", "medium", "large-v3"}:
        model = "base"
    device = str(device or "auto").strip().lower()
    if device not in {"auto", "cuda", "cpu"}:
        device = "auto"
    cmd = [str(whisper_python_path()), str(WHISPER_HELPER), str(src), "--model", model, "--device", device]
    lang = str(language or "auto").strip()
    if lang and lang.lower() != "auto":
        cmd += ["--language", lang]
    proc = subprocess.run(cmd, cwd=str(LAB), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=900, env=hf_env())
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or f"Transcription failed with exit code {proc.returncode}").strip()[-4000:])
    try:
        data = json.loads(proc.stdout)
    except Exception:
        raise RuntimeError("Transcription did not return JSON. stderr: " + proc.stderr[-2000:] + " stdout: " + proc.stdout[-2000:])
    data["source_path"] = str(src)
    data["stderr"] = proc.stderr.strip()[-2000:]
    return data


def save_stt_transcript(path: str, text: str) -> dict[str, Any]:
    src = safe_existing_path(path, [REF_DIR, OUT_DIR, PROFILE_DIR, STT_UPLOAD_DIR])
    text = str(text or "").strip()
    if not text:
        raise ValueError("Transcript text is empty.")
    if inside(src, PROFILE_DIR) and src.parent.exists() and (src.parent / "voice-profile.json").exists():
        transcript_path = src.parent / "transcript.txt"
        transcript_path.write_text(text + "\n", encoding="utf-8")
        try:
            manifest_path = src.parent / "voice-profile.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["transcript_file"] = "transcript.txt"
            manifest["updated_at"] = iso_time()
            manifest["transcript_source"] = "stt-reviewed-save"
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass
    elif inside(src, REF_DIR) or inside(src, STT_UPLOAD_DIR):
        transcript_path = src.with_suffix(".txt")
        transcript_path.write_text(text + "\n", encoding="utf-8")
    elif inside(src, OUT_DIR):
        sidecar = src.with_suffix(src.suffix + ".json")
        meta = read_output_sidecar(src)
        meta["stt_transcript"] = text
        meta["stt_transcript_saved_at"] = iso_time()
        sidecar.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        transcript_path = sidecar
    else:
        raise ValueError("Unsupported STT source location.")
    return {"source_path": str(src), "transcript_path": str(transcript_path), "text": text}

def delete_output_artifacts(value: str) -> dict[str, Any]:
    """Delete one generated output and its local sidecars.

    This is intentionally limited to OUT_DIR so the web UI cannot delete
    arbitrary files. For chunked Chatterbox renders it also removes the hidden
    *_parts folder and concat file tied to that output.
    """
    target = safe_existing_path(value, [OUT_DIR])
    if not target.is_file() or target.suffix.lower() not in AUDIO_EXTS:
        raise ValueError("Only generated audio files inside the output directory can be deleted.")

    deleted: list[str] = []

    def remove_file(path: Path) -> None:
        if path.exists() and path.is_file():
            path.unlink()
            deleted.append(str(path))

    remove_file(target)
    remove_file(target.with_suffix(target.suffix + ".json"))
    remove_file(target.with_suffix(target.suffix + ".concat.txt"))
    remove_file(preview_path_for(target))

    parts_dir = target.parent / (target.stem + "_parts")
    if parts_dir.exists() and parts_dir.is_dir() and inside(parts_dir, OUT_DIR):
        shutil.rmtree(parts_dir)
        deleted.append(str(parts_dir))

    # If this was the last generated file in a batch directory, leave manifest
    # files alone unless the directory is otherwise empty. This avoids deleting
    # batch context unexpectedly, but keeps the tree tidy for fully empty dirs.
    try:
        parent = target.parent
        if parent != OUT_DIR and inside(parent, OUT_DIR) and not any(parent.iterdir()):
            parent.rmdir()
            deleted.append(str(parent))
    except Exception:
        pass

    return {"deleted": deleted, "path": str(target)}


def delete_profile(slug: str) -> dict[str, Any]:
    slug = safe_slug(str(slug or ""), "")
    if not slug:
        raise ValueError("Profile slug is required.")
    target = (PROFILE_DIR / slug).resolve()
    if not inside(target, PROFILE_DIR) or not target.exists() or not target.is_dir():
        raise ValueError("Profile not found.")
    manifest = profile_manifest(target) or {"name": slug, "slug": slug}
    shutil.rmtree(target)
    return {"deleted": True, "slug": slug, "name": manifest.get("name") or slug, "path": str(target)}


def create_profile(
    *,
    name: str,
    audio_bytes: bytes | None = None,
    audio_filename: str = "audio.wav",
    source_audio_path: str = "",
    transcript_text: str = "",
    transcript_bytes: bytes | None = None,
    transcript_filename: str = "transcript.txt",
    speaker: str = "",
    style: str = "",
    notes: str = "",
    source: str = "manual",
    overwrite: bool = False,
) -> dict[str, Any]:
    ensure_dirs()
    display_name = name.strip() or Path(audio_filename).stem or "Voice Profile"
    slug_base = safe_slug(display_name, "voice-profile")
    slug = slug_base
    profile_dir = PROFILE_DIR / slug
    if profile_dir.exists() and not overwrite:
        slug = f"{slug_base}-{uuid.uuid4().hex[:6]}"
        profile_dir = PROFILE_DIR / slug
    profile_dir.mkdir(parents=True, exist_ok=True)

    source_path_obj: Path | None = None
    if source_audio_path:
        source_path_obj = safe_existing_path(source_audio_path, [REF_DIR, OUT_DIR, STT_UPLOAD_DIR])
        if audio_filename == "audio.wav" and source_path_obj.suffix.lower() in AUDIO_EXTS:
            audio_filename = "audio" + source_path_obj.suffix.lower()

    audio_ext = Path(audio_filename).suffix.lower()
    if audio_ext not in AUDIO_EXTS:
        audio_ext = ".wav"
    audio_name = "audio" + audio_ext
    audio_path = profile_dir / audio_name

    if audio_bytes is not None:
        audio_path.write_bytes(audio_bytes)
    elif source_path_obj is not None:
        shutil.copy2(source_path_obj, audio_path)
    else:
        raise ValueError("Profile audio is required.")

    if transcript_bytes is not None:
        try:
            transcript_text = transcript_bytes.decode("utf-8")
        except UnicodeDecodeError:
            transcript_text = transcript_bytes.decode("utf-8", errors="replace")
    transcript_path = profile_dir / "transcript.txt"
    transcript_path.write_text(transcript_text.strip() + ("\n" if transcript_text.strip() else ""), encoding="utf-8")

    manifest = {
        "schema": "tts-lab.voice-profile.v1",
        "name": display_name,
        "slug": slug,
        "speaker": speaker.strip(),
        "style": style.strip(),
        "notes": notes.strip(),
        "audio_file": audio_name,
        "transcript_file": "transcript.txt",
        "created_at": iso_time(),
        "created_by": f"tts-unified-webui {VERSION}",
        "source": source,
        "warning": "Use generated audio as a reference only by explicit choice; clone-of-clone can compound artifacts.",
    }
    (profile_dir / "voice-profile.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    data = profile_manifest(profile_dir)
    if not data:
        raise RuntimeError("Profile was written but could not be read back.")
    return data


def import_profile_zip(zip_bytes: bytes, overwrite: bool = False) -> dict[str, Any]:
    ensure_dirs()
    tmp_dir = PROFILE_DIR / f".import-{uuid.uuid4().hex}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        zip_path = tmp_dir / "profile.zip"
        zip_path.write_bytes(zip_bytes)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if len(names) > 20:
                raise ValueError("Profile ZIP has too many files.")
            for name in names:
                if name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError(f"Unsafe ZIP path: {name}")
            zf.extractall(tmp_dir)
        manifest_path = tmp_dir / "voice-profile.json"
        if not manifest_path.exists():
            # tolerate a one-folder wrapper
            found = list(tmp_dir.glob("*/voice-profile.json"))
            if found:
                manifest_path = found[0]
            else:
                raise ValueError("ZIP must contain voice-profile.json")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("voice-profile.json must be an object")
        name = str(data.get("name") or data.get("slug") or "Imported Voice Profile")
        base = manifest_path.parent
        audio_file = str(data.get("audio_file") or "audio.wav")
        transcript_file = str(data.get("transcript_file") or "transcript.txt")
        audio_path = base / safe_filename(audio_file, "audio.wav")
        transcript_path = base / safe_filename(transcript_file, "transcript.txt")
        if not audio_path.exists():
            audio_candidates = [p for p in base.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
            if not audio_candidates:
                raise ValueError("Profile ZIP must contain an audio file")
            audio_path = audio_candidates[0]
        transcript = read_text_file_if_exists(transcript_path)
        return create_profile(
            name=name,
            audio_bytes=audio_path.read_bytes(),
            audio_filename=audio_path.name,
            transcript_text=transcript,
            speaker=str(data.get("speaker", "")),
            style=str(data.get("style", "")),
            notes=str(data.get("notes", "")),
            source="zip-import",
            overwrite=overwrite,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    created_at: float = field(default_factory=now)
    started_at: float | None = None
    finished_at: float | None = None
    engine: str | None = None
    role: str | None = None
    text: str | None = None
    output: str | None = None
    command: list[str] = field(default_factory=list)
    returncode: int | None = None
    log: str = ""
    error: str | None = None
    warning: str | None = None
    children: list[dict[str, Any]] = field(default_factory=list)
    manifest: str | None = None
    source_path: str | None = None
    transcript: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    cancel_requested: bool = False
    process_pid: int | None = None
    canceled_at: float | None = None

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        if self.output:
            p = Path(self.output)
            if p.exists() and self.status != "running":
                try:
                    data["audio_url"] = preview_url_for(p)
                    data["preview_url"] = preview_url_for(p)
                    data["wav_url"] = audio_url_for(p)
                    data["output_path"] = str(p)
                    data["duration_seconds"] = audio_duration_seconds(p)
                    meta = read_output_sidecar(p)
                    data["reference_audio"] = meta.get("reference_audio", "")
                    data["reference_transcript"] = meta.get("reference_transcript", "")
                    data["metadata"] = meta
                except ValueError:
                    data["audio_url"] = versioned_url(f"/preview-audio/{p.name}", p)
                    data["preview_url"] = data["audio_url"]
                    data["wav_url"] = versioned_url(f"/audio/{p.name}", p)
                    data["output_path"] = str(p)
                    data["duration_seconds"] = audio_duration_seconds(p)
        if self.kind in {"audio", "video"} and isinstance(data.get("result"), dict):
            res = data["result"]
            for key in ("source_waveform", "output_waveform"):
                val = str(res.get(key) or "")
                if val:
                    wp = Path(val)
                    if wp.exists() and inside(wp.resolve(), AUDIO_LAB_DIR):
                        res[key + "_url"] = versioned_url("/audio-lab-waveform/" + wp.name, wp)
        if self.kind == "stt":
            if self.source_path:
                data["source_path"] = self.source_path
                try:
                    data["duration_seconds"] = audio_duration_seconds(Path(self.source_path))
                except Exception:
                    pass
            if self.transcript:
                data["transcript"] = self.transcript
            if self.result:
                data["result"] = self.result
        if self.manifest:
            data["manifest_url"] = f"/manifest/{Path(self.manifest).name}"
        return data


class JobManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[str, Job] = self._load_history()
        self.running_procs: dict[str, subprocess.Popen] = {}
        self.q: queue.Queue[tuple[Job, dict[str, Any]]] = queue.Queue()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()

    def _job_json_path(self, job_id: str) -> Path:
        return JOB_DIR / f"{safe_slug(job_id)}.json"

    def _job_log_path(self, job_id: str) -> Path:
        return JOB_DIR / f"{safe_slug(job_id)}.log"

    def _load_history(self) -> dict[str, Job]:
        ensure_dirs()
        jobs: dict[str, Job] = {}
        fields = set(Job.__dataclass_fields__.keys())
        for path in sorted(JOB_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:250]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                kwargs = {k: v for k, v in data.items() if k in fields}
                if not kwargs.get("id"):
                    continue
                job = Job(**kwargs)
                log_path = self._job_log_path(job.id)
                if log_path.exists():
                    job.log = read_tail_text(log_path)
                jobs[job.id] = job
            except Exception as exc:
                print(f"WARNING: could not load job history {path}: {exc}")

        # v0.41 and earlier kept completed output metadata but not job logs.
        # Recover those outputs into the Jobs list with an honest placeholder so
        # old work is still visible after restarting the web UI.
        for p in sorted(OUT_DIR.rglob("*.wav"), key=lambda x: x.stat().st_mtime, reverse=True)[:200]:
            try:
                rel = p.relative_to(OUT_DIR)
                if any(part.endswith("_parts") for part in rel.parts):
                    continue
                meta = read_output_sidecar(p)
                hist_id = str(meta.get("job_id") or uuid.uuid5(uuid.NAMESPACE_URL, str(p.resolve())))
                if hist_id in jobs:
                    continue
                st = p.stat()
                meta_kind = str(meta.get("kind", ""))
                if meta_kind == "resemble-enhance-output":
                    function_label = str(meta.get("function_label") or meta.get("mode") or "resemble").strip()
                    source_label = str(meta.get("source_label") or Path(str(meta.get("source_audio") or "")).name or p.name).strip()
                    jobs[hist_id] = Job(
                        id=hist_id,
                        kind="resemble",
                        status="done",
                        created_at=st.st_mtime,
                        finished_at=st.st_mtime,
                        engine=str(meta.get("engine", "resemble-enhance")),
                        role=function_label,
                        text=f"{function_label} speech: {source_label}".strip(),
                        output=str(p),
                        source_path=str(meta.get("source_audio", "")),
                        result=meta,
                        log=(
                            "Recovered Resemble Enhance output from its sidecar metadata. "
                            "The original job log was not available after upgrade/restart, but the output, source, mode, and metadata were preserved.\n"
                        ),
                    )
                elif meta_kind == "audio-lab-output":
                    jobs[hist_id] = Job(
                        id=hist_id,
                        kind="audio",
                        status="done",
                        created_at=st.st_mtime,
                        finished_at=st.st_mtime,
                        engine=str(meta.get("engine", "audio-lab")),
                        role=str(meta.get("function_label") or meta.get("operation") or "audio-lab"),
                        text=str(meta.get("source_label") or meta.get("source_audio") or p.name),
                        output=str(p),
                        source_path=str(meta.get("source_audio", "")),
                        result=meta,
                        log=(
                            "Recovered Audio Lab output from its sidecar metadata. "
                            "The original job log was not available after upgrade/restart.\n"
                        ),
                    )
                elif meta_kind == "video-intake-output":
                    jobs[hist_id] = Job(
                        id=hist_id,
                        kind="video",
                        status="done",
                        created_at=st.st_mtime,
                        finished_at=st.st_mtime,
                        engine=str(meta.get("engine", "video-intake")),
                        role=str(meta.get("function_label") or "extracted"),
                        text=str(meta.get("source_label") or meta.get("source_media") or p.name),
                        output=str(p),
                        source_path=str(meta.get("source_media", "")),
                        result=meta,
                        log=(
                            "Recovered Video Intake extracted-audio output from its sidecar metadata. "
                            "The original job log was not available after upgrade/restart.\n"
                        ),
                    )
                else:
                    jobs[hist_id] = Job(
                        id=hist_id,
                        kind="historical-output",
                        status="done",
                        created_at=st.st_mtime,
                        finished_at=st.st_mtime,
                        engine=str(meta.get("engine", "")),
                        role=str(meta.get("role", "")),
                        text=str(meta.get("text", "")),
                        output=str(p),
                        log=(
                            "No saved subprocess log exists for this completed output. "
                            "It was created before v0.42 job-history logging or without recognizable sidecar metadata. "
                            "Future jobs will keep persistent logs across web UI restarts.\n"
                        ),
                    )
            except Exception:
                continue
        return jobs

    def _persist_job(self, job: Job) -> None:
        try:
            ensure_dirs()
            data = asdict(job)
            data["log"] = ""  # stored separately so job JSON stays readable
            tmp = self._job_json_path(job.id).with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._job_json_path(job.id))
            self._job_log_path(job.id).write_text(job.log, encoding="utf-8")
        except Exception as exc:
            print(f"WARNING: could not persist job {job.id}: {exc}")

    def add(self, job: Job, payload: dict[str, Any]) -> Job:
        with self.lock:
            self.jobs[job.id] = job
            self._persist_job(job)
        self.q.put((job, payload))
        return job

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return {"ok": False, "message": "Job not found."}
            if job.status in {"done", "error", "canceled"}:
                return {"ok": False, "message": f"Job is already {job.status}."}
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "canceled"
                job.canceled_at = now()
                job.finished_at = job.canceled_at
                job.error = None
                self._persist_job(job)
                return {"ok": True, "message": "Queued job canceled."}
            job.status = "canceling"
            self._persist_job(job)
            proc = self.running_procs.get(job_id)
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            def hard_kill() -> None:
                time.sleep(4)
                if proc.poll() is None:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            threading.Thread(target=hard_kill, daemon=True).start()
            return {"ok": True, "message": "Abort requested; stopping subprocess."}
        return {"ok": True, "message": "Abort requested."}

    def _is_cancel_requested(self, job: Job) -> bool:
        with self.lock:
            return bool(job.cancel_requested or job.status in {"canceling", "canceled"})

    def _mark_canceled(self, job: Job, message: str = "Canceled by user.") -> None:
        self._append_log(job, "\n" + message + "\n")
        self._set(job, status="canceled", error=None, warning=message, finished_at=now(), canceled_at=now(), process_pid=None)

    def list_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]
        return [j.public() for j in jobs]

    def _set(self, job: Job, **updates: Any) -> None:
        with self.lock:
            for k, v in updates.items():
                setattr(job, k, v)
            self._persist_job(job)

    def _append_log(self, job: Job, chunk: str) -> None:
        with self.lock:
            job.log += chunk
            if len(job.log) > 128000:
                job.log = job.log[-128000:]
            self._persist_job(job)

    def _worker_loop(self) -> None:
        while True:
            job, payload = self.q.get()
            try:
                if self._is_cancel_requested(job):
                    if job.status != "canceled":
                        self._mark_canceled(job)
                    continue
                if job.kind == "single":
                    self._run_single(job, payload)
                elif job.kind == "batch":
                    self._run_batch(job, payload)
                elif job.kind == "stt":
                    self._run_stt(job, payload)
                elif job.kind == "setup":
                    self._run_setup(job, payload)
                elif job.kind == "audio":
                    self._run_audio_lab(job, payload)
                elif job.kind == "video":
                    self._run_video_intake(job, payload)
                elif job.kind == "resemble":
                    self._run_resemble_enhance_job(job, payload)
                else:
                    raise RuntimeError(f"Unknown job kind: {job.kind}")
            except Exception as exc:
                self._set(job, status="error", error=str(exc), finished_at=now())
            finally:
                self.q.task_done()

    def _build_command(self, payload: dict[str, Any], output: Path) -> list[str]:
        engine = str(payload.get("engine", "")).strip().lower()
        if engine not in ENGINE_META:
            raise ValueError(f"Unknown engine: {engine}")
        text = str(payload.get("text", "")).strip()
        if not text:
            raise ValueError("Text is required.")
        ref = str(payload.get("ref", str(DEFAULT_REF))).strip() or str(DEFAULT_REF)
        ref_text = str(payload.get("ref_text", "")).strip()
        x_vector_only = bool(payload.get("x_vector_only", engine == "qwen3"))

        cmd = [str(LAUNCHER), "synth", engine, "--text", text, "--ref", ref, "--out", str(output)]
        # Qwen3 x-vector-only mode is meant to avoid depending on the exact
        # reference transcript. Do not pass --ref-text in that mode; earlier
        # builds sent both, which made troubleshooting confusing.
        if ref_text and not (engine == "qwen3" and x_vector_only):
            cmd += ["--ref-text", ref_text]
        if engine == "qwen3" and x_vector_only:
            cmd += ["--x-vector-only"]
        return cmd

    def _run_subprocess(self, job: Job, cmd: list[str], cwd: Path | None = None) -> int:
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        self._set(job, command=cmd)
        self._append_log(job, "$ " + shlex.join(cmd) + "\n\n")
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd or LAB),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        with self.lock:
            self.running_procs[job.id] = proc
            job.process_pid = proc.pid
            self._persist_job(job)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._append_log(job, line)
            proc.wait()
            self._append_log(job, f"\nProcess exited with return code: {proc.returncode}\n")
            self._set(job, returncode=proc.returncode, process_pid=None)
            return proc.returncode
        finally:
            with self.lock:
                self.running_procs.pop(job.id, None)
                job.process_pid = None
                self._persist_job(job)

    def _run_capture_subprocess(self, job: Job, cmd: list[str], timeout: int = 900, cwd: Path | None = None, env: dict[str, str] | None = None) -> tuple[int, str, str, bool]:
        self._set(job, command=cmd)
        self._append_log(job, "$ " + shlex.join(cmd) + "\n\n")
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd or LAB),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env or os.environ.copy(),
            start_new_session=True,
        )
        with self.lock:
            self.running_procs[job.id] = proc
            job.process_pid = proc.pid
            self._persist_job(job)
        timed_out = False
        try:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except Exception:
                    proc.terminate()
                stdout, stderr = proc.communicate(timeout=10)
            if stderr:
                self._append_log(job, stderr + ("" if stderr.endswith("\n") else "\n"))
            if stdout:
                self._append_log(job, stdout + ("" if stdout.endswith("\n") else "\n"))
            self._set(job, returncode=proc.returncode, process_pid=None)
            return int(proc.returncode or 0), stdout or "", stderr or "", timed_out
        finally:
            with self.lock:
                self.running_procs.pop(job.id, None)
                job.process_pid = None
                self._persist_job(job)

    def _normalize_wav_for_browser(self, job: Job, path: Path) -> bool:
        """Rewrite WAV files as PCM16 with a fresh RIFF header.

        VLC is forgiving of odd/streamed WAV headers, but browser audio
        elements often trust the header and may stop early. Rewriting through
        ffmpeg makes the same file browser-safe without changing the user's
        download path.
        """
        if path.suffix.lower() != ".wav" or not path.exists():
            return True
        tmp = path.with_name(path.stem + ".browser_safe.tmp.wav")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(path),
            "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le",
            str(tmp),
        ]
        self._append_log(job, "\n$ " + shlex.join(cmd) + "\n")
        rc = subprocess.call(cmd, cwd=str(LAB))
        if rc == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(path)
            self._append_log(job, "Rewrote WAV header/container for browser playback.\n")
            ensure_mp3_preview(path, lambda msg: self._append_log(job, msg))
            return True
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        self._append_log(job, "Warning: browser-safe WAV rewrite failed; keeping original output.\n")
        return False

    def _concat_wavs(self, job: Job, pieces: list[Path], output: Path) -> bool:
        if not pieces:
            return False
        concat_file = output.with_suffix(output.suffix + ".concat.txt")
        def q(path: Path) -> str:
            return str(path).replace("'", "'\\''")
        concat_file.write_text("".join(f"file '{q(p)}'\n" for p in pieces), encoding="utf-8")
        # Always re-encode instead of stream-copying WAV chunks. Stream-copy
        # can create files VLC plays but browser audio cuts short.
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_file),
            "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le",
            str(output),
        ]
        self._append_log(job, "\n$ " + shlex.join(cmd) + "\n")
        rc = subprocess.call(cmd, cwd=str(LAB))
        return rc == 0 and output.exists() and self._normalize_wav_for_browser(job, output)

    def _run_chunked(self, job: Job, payload: dict[str, Any], output: Path, chunks: list[str]) -> int:
        pieces: list[Path] = []
        chunk_dir = output.parent / (output.stem + "_parts")
        chunk_dir.mkdir(parents=True, exist_ok=True)
        cooldown = float(os.environ.get("TTS_WEBUI_COOLDOWN_SECONDS", "2"))
        self._append_log(job, f"\nSplitting into {len(chunks)} short render chunks to avoid truncated output.\n")
        for i, chunk in enumerate(chunks, start=1):
            if self._is_cancel_requested(job):
                return -15
            part = chunk_dir / f"part_{i:03d}.wav"
            part_payload = dict(payload)
            part_payload["text"] = chunk
            self._append_log(job, f"\n--- chunk {i}/{len(chunks)}: {chunk} ---\n")
            cmd = self._build_command(part_payload, part)
            rc = self._run_subprocess(job, cmd)
            if rc != 0 or not part.exists():
                return rc
            pieces.append(part)
            if cooldown > 0 and i < len(chunks):
                self._append_log(job, f"Cooling down {cooldown:g}s before next chunk.\n")
                for _ in range(int(max(1, cooldown * 10))):
                    if self._is_cancel_requested(job):
                        return -15
                    time.sleep(0.1)
        if self._is_cancel_requested(job):
            return -15
        return 0 if self._concat_wavs(job, pieces, output) else 1

    def _run_setup(self, job: Job, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "").strip()
        if action == "whisper-gpu-test":
            self._run_whisper_gpu_test(job, payload)
            return
        if action == "resemble-enhance":
            self._run_resemble_enhance_setup(job, payload)
            return
        if action == "resemble-git-lfs":
            self._run_resemble_git_lfs_repair(job, payload)
            return
        if action != "whisper-cuda":
            raise ValueError("Unknown setup action.")
        if not WHISPER_CUDA_INSTALLER.exists():
            raise RuntimeError(f"CUDA helper not found: {WHISPER_CUDA_INSTALLER}")
        self._set(job, status="running", started_at=now(), engine="setup", role="whisper-cuda", text="Install / repair Whisper GPU support")
        rc = self._run_subprocess(job, [str(WHISPER_CUDA_INSTALLER)], cwd=LAB)
        if rc == 0:
            libs = whisper_nvidia_lib_dirs()
            msg = "Whisper CUDA libraries installed. "
            if libs:
                msg += "Detected NVIDIA library dirs: " + ", ".join(libs[:6])
            else:
                msg += "No NVIDIA library dirs were detected yet; restart or inspect the setup log."
            self._set(job, status="done", warning="Restart Web UI or run GPU test if needed.", result={"message": msg, "nvidia_lib_dirs": libs}, finished_at=now())
        else:
            self._set(job, status="error", error=oom_message(rc), finished_at=now())

    def _run_resemble_git_lfs_repair(self, job: Job, payload: dict[str, Any]) -> None:
        """Install/repair Git LFS for Resemble model downloads inside the isolated env when possible."""
        self._set(job, status="running", started_at=now(), engine="setup", role="resemble-git-lfs", text="Install / repair Resemble Git LFS model downloader")
        env_name = resemble_env_name()
        conda = conda_exe_path()
        env_py = resemble_env_python_path()
        env_bin = resemble_env_bin_path()
        self._append_log(job, "Resemble Enhance Git LFS repair\n")
        self._append_log(job, "Resemble uses Git LFS to download model files. If Git LFS is missing, jobs fail with: git: 'lfs' is not a git command.\n\n")
        self._append_log(job, f"Conda env name: {env_name}\n")
        self._append_log(job, f"Detected env python: {env_py or '<none>'}\n")
        self._append_log(job, f"Detected env bin: {env_bin or '<none>'}\n")
        self._append_log(job, f"Detected conda: {conda or '<none>'}\n\n")
        before = resemble_git_lfs_status()
        self._append_log(job, "Before repair Git LFS status:\n" + json.dumps(before, indent=2) + "\n\n")
        rc = 0
        if before.get("available"):
            self._append_log(job, "Git LFS is already available from the Resemble runtime PATH. No install needed.\n")
        elif conda:
            cmd = [str(conda), "install", "-n", env_name, "-c", "conda-forge", "git-lfs", "-y"]
            self._append_log(job, "$ " + shlex.join(cmd) + "\n\n")
            rc = self._run_subprocess(job, cmd, cwd=LAB)
            if self._is_cancel_requested(job) or rc in {-15, -9, 143, 137}:
                self._mark_canceled(job)
                return
            if rc == 0:
                env = resemble_runtime_env()
                init_cmd = ["git", "lfs", "install", "--skip-repo"]
                self._append_log(job, "\n$ " + shlex.join(init_cmd) + "\n")
                try:
                    proc = subprocess.run(init_cmd, cwd=str(LAB), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, timeout=60)
                    self._append_log(job, proc.stdout or "")
                    self._append_log(job, f"git lfs install return code: {proc.returncode}\n")
                except Exception as exc:
                    self._append_log(job, f"git lfs install check failed: {exc}\n")
        else:
            self._append_log(job, "Conda was not detected, so the Web UI cannot install git-lfs into the isolated conda env.\n")
            self._append_log(job, "If you are using venv mode, install Git LFS at the OS/user level or recreate Resemble in conda mode.\n")
            rc = 1
        after = resemble_git_lfs_status()
        self._append_log(job, "\nAfter repair Git LFS status:\n" + json.dumps(after, indent=2) + "\n")
        result = {"before": before, "after": after, "resemble_status": resemble_status_payload()}
        if after.get("available"):
            self._set(job, status="done", result=result, warning="Git LFS is available. Try the Resemble denoise/enhance job again; the first run may download model files.", finished_at=now())
        else:
            msg = "Git LFS is still not available to the Resemble runtime. See the repair log."
            if rc != 0:
                msg += f" Repair command exit code: {rc}."
            self._set(job, status="error", error=msg, result=result, finished_at=now())

    def _run_resemble_enhance_setup(self, job: Job, payload: dict[str, Any]) -> None:
        if not RESEMBLE_INSTALLER.exists():
            raise RuntimeError(f"Resemble Enhance installer not found: {RESEMBLE_INSTALLER}. Re-run the Web UI installer for v0.76 or newer.")
        mode = str(payload.get("mode") or "auto").strip().lower()
        if mode not in {"auto", "conda", "venv"}:
            mode = "auto"
        self._set(job, status="running", started_at=now(), engine="setup", role="resemble-enhance", text=f"Install / repair Resemble Enhance isolated environment ({mode})")
        self._append_log(job, "Resemble Enhance setup is intentionally isolated from the main Web UI and TTS engine environments.\n")
        self._append_log(job, f"Installer: {RESEMBLE_INSTALLER}\nEngine root: {RESEMBLE_ROOT}\nOutput dir: {RESEMBLE_OUTPUT_DIR}\nInstall mode request: {mode}\n\n")
        env = os.environ.copy()
        env["TTS_RESEMBLE_INSTALL_MODE"] = mode
        self._set(job, command=[str(RESEMBLE_INSTALLER)])
        self._append_log(job, "$ " + shlex.join([str(RESEMBLE_INSTALLER)]) + "\n\n")
        proc = subprocess.Popen(
            [str(RESEMBLE_INSTALLER)],
            cwd=str(LAB),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        with self.lock:
            self.running_procs[job.id] = proc
            job.process_pid = proc.pid
            self._persist_job(job)
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._append_log(job, line)
            proc.wait()
            rc = int(proc.returncode or 0)
            self._set(job, returncode=rc, process_pid=None)
        finally:
            with self.lock:
                self.running_procs.pop(job.id, None)
                job.process_pid = None
                self._persist_job(job)
        if self._is_cancel_requested(job) or rc in {-15, -9, 143, 137}:
            self._mark_canceled(job)
            return
        status = resemble_status_payload()
        if rc == 0 and status.get("ready"):
            self._set(job, status="done", result=status, warning="Resemble Enhance installed. Use the Resemble Enhance tab to check status; enhancement workflow will remain isolated from Audio Lab until it is proven locally.", finished_at=now())
        elif rc == 0:
            self._set(job, status="error", result=status, error="Installer finished but no runnable resemble-enhance command was detected. Open the job log for details.", finished_at=now())
        else:
            self._set(job, status="error", result=status, error=oom_message(rc), finished_at=now())

    def _run_whisper_gpu_test(self, job: Job, payload: dict[str, Any]) -> None:
        status = whisper_status_payload()
        if not status.get("ready"):
            raise RuntimeError("Faster-Whisper is not ready: " + str(status.get("error", "")))
        raw_path = str(payload.get("path") or "").strip()
        if raw_path:
            src = safe_existing_path(raw_path, [REF_DIR, OUT_DIR, PROFILE_DIR, STT_UPLOAD_DIR])
        else:
            candidates = [p for p in sorted(STT_UPLOAD_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True) if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
            if not candidates:
                raise RuntimeError("Choose or upload an STT audio source before testing GPU transcription support. The GPU test must use real audio, not silence.")
            src = candidates[0]
        model = str(payload.get("model") or "tiny").strip().lower()
        if model not in {"tiny", "base", "small", "medium", "large-v3"}:
            model = "tiny"
        language = str(payload.get("language") or "auto").strip()
        cmd = self._stt_command(src, model, language, "cuda", "float16")
        self._set(job, status="running", started_at=now(), engine="setup", role="whisper-gpu-test", text=f"Real CUDA transcription test: {src.name} — model {model}", source_path=str(src), command=cmd)
        self._append_log(job, "This test intentionally uses Device=cuda and Compute=float16 with the same helper used by normal STT jobs. It should fail if libcublas/cuDNN are missing.\n\n")
        rc, stdout, stderr, timed_out = self._run_capture_subprocess(job, cmd, timeout=300, cwd=LAB, env=hf_env())
        if self._is_cancel_requested(job):
            self._mark_canceled(job)
            return
        if timed_out:
            self._set(job, status="error", error="GPU test timed out. See log.", finished_at=now())
            return
        if rc != 0:
            raw = (stderr or stdout or f"GPU test failed with exit code {rc}")
            self._set(job, status="error", error="GPU transcription test failed. " + self._human_stt_error(raw), finished_at=now())
            return
        try:
            data = json.loads(stdout)
        except Exception:
            self._set(job, status="error", error="GPU test completed but did not return parseable JSON. See log.", finished_at=now())
            return
        data["source_path"] = str(src)
        if data.get("device") == "cuda" and str(data.get("compute_type", "")).lower() == "float16":
            self._set(job, status="done", result=data, transcript=str(data.get("text") or "").strip(), finished_at=now())
        else:
            self._set(job, status="error", error="GPU test ran but did not report device=cuda and compute_type=float16. See log.", result=data, finished_at=now())

    def _stt_command(self, src: Path, model: str, language: str, device: str, compute_type: str = "auto") -> list[str]:
        cmd = [str(whisper_python_path()), str(WHISPER_HELPER), str(src), "--model", model, "--device", device, "--compute-type", compute_type]
        lang = str(language or "auto").strip()
        if lang and lang.lower() != "auto":
            cmd += ["--language", lang]
        return cmd

    def _human_stt_error(self, raw: str) -> str:
        text = str(raw or "").strip()
        if "libcublas.so.12" in text or "libcudnn" in text:
            return (
                "Whisper GPU mode could not load NVIDIA CUDA runtime libraries. "
                "Try Device = cpu for now, or install the optional Whisper CUDA libraries and restart the web UI. "
                "The full traceback is in the job log."
            )
        if "float16" in text and "CPU" in text or "float16 compute type" in text:
            return (
                "Whisper was asked to use float16 on a backend that does not support it. "
                "This build defaults CPU jobs to int8; try Device = cpu again. The full traceback is in the job log."
            )
        if "HF_TOKEN" in text or "unauthenticated requests to the HF Hub" in text:
            return (
                "Hugging Face model download/authentication warning. Add a read-only HF token for more reliable model downloads. "
                "The full message is in the job log."
            )
        return text[-600:] or "Transcription failed. See job log."

    def _run_stt(self, job: Job, payload: dict[str, Any]) -> None:
        src = safe_existing_path(str(payload.get("path", "")), [REF_DIR, OUT_DIR, PROFILE_DIR, STT_UPLOAD_DIR])
        if src.suffix.lower() not in AUDIO_EXTS:
            raise ValueError("Selected STT source is not an audio file.")
        status = whisper_status_payload()
        if not status.get("ready"):
            raise RuntimeError("Faster-Whisper is not ready. " + str(status.get("error", "")) + " Run: " + str(status.get("install_command", "")))
        model = str(payload.get("model") or "base").strip().lower()
        if model not in {"tiny", "base", "small", "medium", "large-v3"}:
            model = "base"
        device = str(payload.get("device") or "auto").strip().lower()
        if device not in {"auto", "cuda", "cpu"}:
            device = "auto"
        language = str(payload.get("language") or "auto").strip()
        compute_type = str(payload.get("compute_type") or "auto").strip().lower() or "auto"
        role = src.name
        text = f"{src.name} — model {model}, device {device}"
        self._set(job, status="running", started_at=now(), engine="faster-whisper", role=role, text=text, source_path=str(src))
        cmd = self._stt_command(src, model, language, device, compute_type)
        rc, stdout, stderr, timed_out = self._run_capture_subprocess(job, cmd, timeout=900, cwd=LAB, env=hf_env())
        if self._is_cancel_requested(job):
            self._mark_canceled(job)
            return
        if timed_out:
            self._set(job, status="error", error="Transcription timed out after 15 minutes. Try a smaller model or shorter audio.", finished_at=now())
            return
        if rc != 0:
            raw = (stderr or stdout or f"Transcription failed with exit code {rc}")
            self._set(job, status="error", error=self._human_stt_error(raw), finished_at=now())
            return
        try:
            data = json.loads(stdout)
        except Exception:
            self._set(job, status="error", error="Transcription completed but did not return parseable JSON. See job log.", finished_at=now())
            return
        data["source_path"] = str(src)
        data["stderr"] = (stderr or "").strip()[-2000:]
        warning = str(data.get("fallback_warning") or "").strip()
        transcript = str(data.get("text") or "").strip()
        self._set(job, status="done", transcript=transcript, result=data, warning=warning or None, finished_at=now())

    def _run_single(self, job: Job, payload: dict[str, Any]) -> None:
        engine = str(payload.get("engine", "")).strip().lower()
        role = str(payload.get("role", "single")).strip() or "single"
        text = str(payload.get("text", "")).strip()
        output = Path(str(payload.get("output") or unique_wav(f"{role}_{engine}")))
        self._set(job, status="running", started_at=now(), engine=engine, role=role, text=text, output=str(output))
        chunks = split_synthesis_text(text)
        split_on_sentences = bool(payload.get("split_on_sentences", engine == "chatterbox"))
        if engine == "chatterbox" and split_on_sentences and len(chunks) > 1:
            rc = self._run_chunked(job, payload, output, chunks)
        else:
            cmd = self._build_command(payload, output)
            rc = self._run_subprocess(job, cmd)
        if self._is_cancel_requested(job) or rc in {-15, -9, 143, 137}:
            try:
                if output.exists():
                    output.unlink()
            except Exception:
                pass
            self._mark_canceled(job)
        elif rc == 0 and output.exists():
            self._normalize_wav_for_browser(job, output)
            write_output_sidecar(output, payload, job, role=role)
            self._set(job, status="done", finished_at=now())
        else:
            self._set(job, status="error", error=oom_message(rc), finished_at=now())


    def _run_audio_lab(self, job: Job, payload: dict[str, Any]) -> None:
        src = safe_existing_path(str(payload.get("path", "")), [REF_DIR, OUT_DIR, PROFILE_DIR, STT_UPLOAD_DIR, AUDIO_LAB_DIR])
        if src.suffix.lower() not in AUDIO_EXTS:
            raise ValueError("Selected Audio Lab source is not an audio file.")
        name = str(payload.get("name") or "").strip()
        fmt_choice = str(payload.get("format") or "unchanged").lower().strip()
        fmt = audio_lab_output_format(src, fmt_choice)
        output = audio_lab_output_path(
            src,
            fmt,
            custom_text=name,
            custom_mode=str(payload.get("name_mode") or "none"),
            date_mode=str(payload.get("date_mode") or "none"),
            version_mode=str(payload.get("version_mode") or "collision"),
            function_mode=str(payload.get("function_mode") or "none"),
            filename_template=str(payload.get("filename_template") or ""),
        )
        start = max(0.0, float(payload.get("trim_start") or 0.0))
        dur_raw = str(payload.get("trim_duration") or "").strip()
        duration = max(0.0, float(dur_raw)) if dur_raw else 0.0
        sr_raw = str(payload.get("sample_rate") or "unchanged").strip().lower()
        sample_rate = int(sr_raw) if sr_raw.isdigit() and int(sr_raw) in {16000, 22050, 24000, 44100, 48000} else None
        ch_raw = str(payload.get("channels") or "unchanged").strip().lower()
        channels = 1 if ch_raw in {"1", "mono"} else (2 if ch_raw in {"2", "stereo"} else None)
        mp3_bitrate = str(payload.get("mp3_bitrate") or "192k").strip().lower()
        if mp3_bitrate not in {"96k", "128k", "192k", "256k", "320k"}:
            mp3_bitrate = "192k"
        normalize = bool(payload.get("normalize", True))
        source_wave = audio_lab_waveform_path(src, "before")
        create_waveform_svg(src, source_wave)
        cmd = ["ffmpeg", "-y", "-hide_banner"]
        if start > 0:
            cmd += ["-ss", f"{start:g}"]
        cmd += ["-i", str(src)]
        if duration > 0:
            cmd += ["-t", f"{duration:g}"]
        cmd += ["-vn"]
        if normalize:
            cmd += ["-af", "dynaudnorm=f=150:g=15"]
        if sample_rate:
            cmd += ["-ar", str(sample_rate)]
        if channels:
            cmd += ["-ac", str(channels)]
        if fmt == "wav":
            cmd += ["-c:a", "pcm_s16le"]
        elif fmt == "mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", mp3_bitrate]
        elif fmt == "flac":
            cmd += ["-c:a", "flac"]
        cmd += [str(output)]
        self._set(job, status="running", started_at=now(), engine="audio-lab", role=output.stem, text=f"Process audio: {src.name}", source_path=str(src), output=str(output), command=cmd)
        rc = self._run_subprocess(job, cmd, cwd=LAB)
        if self._is_cancel_requested(job) or rc in {-15, -9, 143, 137}:
            try:
                if output.exists():
                    output.unlink()
            except Exception:
                pass
            self._mark_canceled(job)
        elif rc == 0 and output.exists():
            ensure_mp3_preview(output, lambda msg: self._append_log(job, msg))
            output_wave = audio_lab_waveform_path(output, "after")
            create_waveform_svg(output, output_wave)
            meta = {
                "kind": "audio-lab-output",
                "created_at": iso_time(),
                "job_id": job.id,
                "source_audio": str(src),
                "output_audio": str(output),
                "output_format": fmt,
                "requested_output_format": fmt_choice,
                "trim_start": start,
                "trim_duration": duration,
                "sample_rate": sample_rate or "unchanged",
                "channels": channels or "unchanged",
                "mp3_bitrate": mp3_bitrate if fmt == "mp3" else "",
                "naming": {
                    "custom_text": name,
                    "custom_mode": str(payload.get("name_mode") or "none"),
                    "function_mode": str(payload.get("function_mode") or "none"),
                    "date_mode": str(payload.get("date_mode") or "none"),
                    "version_mode": str(payload.get("version_mode") or "collision"),
                    "filename_template": str(payload.get("filename_template") or ""),
                    "function_label": "clean",
                },
                "normalize_dynaudnorm": normalize,
                "source_waveform": str(source_wave) if source_wave.exists() else "",
                "output_waveform": str(output_wave) if output_wave.exists() else "",
            }
            output.with_suffix(output.suffix + ".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            self._set(job, status="done", result=meta, finished_at=now())
        else:
            self._set(job, status="error", error=oom_message(rc), finished_at=now())

    def _download_video_url(self, job: Job, url: str, work_dir: Path) -> Path:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL import requires a normal http(s) page or media URL.")
        work_dir.mkdir(parents=True, exist_ok=True)
        yt = shutil.which("yt-dlp")
        candidates = discover_video_dl_candidates()
        listing = video_dl_dir_listing()
        self._append_log(job, "Video Intake URL import diagnostics\n")
        self._append_log(job, f"URL: {url}\n")
        self._append_log(job, f"Work directory: {work_dir}\n")
        self._append_log(job, f"Helper directory: {VIDEO_DL_DIR} (exists: {VIDEO_DL_DIR.exists()}, is_dir: {VIDEO_DL_DIR.is_dir()})\n")
        if listing:
            self._append_log(job, "Helper directory entries: " + ", ".join(listing) + "\n")
        else:
            self._append_log(job, "Helper directory entries: <none or not readable>\n")
        self._append_log(job, "Recognized /home/user/video-dl runnable candidates: " + (", ".join(p.name for p in candidates) if candidates else "<none>") + "\n")
        self._append_log(job, "yt-dlp on PATH: " + (yt or "<not found>") + "\n")
        self._append_log(job, "TTS_VIDEO_DL_CMD: " + ("configured" if VIDEO_DL_CMD else "<not set>") + "\n")
        commands = build_video_download_commands(url, work_dir)
        self._append_log(job, f"Total URL importer command candidates: {len(commands)}\n")
        if not commands:
            self._append_log(job,
                "\nNo runnable URL importer was found. The directory may exist, but the web UI only runs known executable/script entrypoints.\n"
                "Fix options:\n"
                "  1. Put an executable script named video-dl, download, download-video, run.sh, main.py, app.py, cli.py, downloader.py, download_video.py, or video_downloader.py in /home/user/video-dl; or\n"
                "  2. Install yt-dlp on PATH; or\n"
                "  3. Start the web UI with TTS_VIDEO_DL_CMD containing {url} and {out}, for example:\n"
                "     TTS_VIDEO_DL_CMD='/home/user/video-dl/YOUR_TOOL {url} {out}' ./start.sh\n"
            )
            raise RuntimeError(
                "URL import is not configured. /home/user/video-dl may exist, but no runnable helper was recognized. "
                "Open the job log for directory details, install yt-dlp, or set TTS_VIDEO_DL_CMD with {url} and {out} placeholders."
            )
        allowed_roots = [work_dir]
        if VIDEO_DL_DIR.exists():
            allowed_roots.append(VIDEO_DL_DIR)
        errors: list[str] = []
        for label, cmd, cwd in commands:
            if self._is_cancel_requested(job):
                raise RuntimeError("Canceled by user.")
            before = now()
            self._append_log(job, f"\nTrying URL import via {label}.\n")
            self._append_log(job, f"Command working directory: {cwd}\n")
            env = os.environ.copy()
            env.setdefault("OUTPUT_DIR", str(work_dir))
            env.setdefault("OUT_DIR", str(work_dir))
            env.setdefault("DOWNLOAD_DIR", str(work_dir))
            self._append_log(job, f"OUTPUT_DIR/OUT_DIR/DOWNLOAD_DIR set to: {work_dir}\n")
            try:
                rc, stdout, stderr, timed_out = self._run_capture_subprocess(job, cmd, timeout=1800, cwd=cwd, env=env)
            except Exception as exc:
                errors.append(f"{label}: could not start command: {exc}")
                self._append_log(job, f"Command start failed for {label}: {exc}\n")
                continue
            if self._is_cancel_requested(job):
                raise RuntimeError("Canceled by user.")
            if timed_out:
                errors.append(f"{label}: timed out")
                self._append_log(job, f"{label} timed out.\n")
                continue
            if rc != 0:
                errors.append(f"{label}: exit {rc}")
                self._append_log(job, f"{label} failed with exit code {rc}.\n")
                continue
            found = newest_media_file(work_dir, before - 1.0)
            if not found and VIDEO_DL_DIR.exists():
                found = newest_media_file(VIDEO_DL_DIR, before - 1.0)
            if not found:
                found = parse_existing_media_path((stdout or "") + "\n" + (stderr or ""), allowed_roots)
                if found and not inside(found, work_dir):
                    copied = work_dir / safe_filename(found.name, "downloaded-video")
                    if copied.exists():
                        copied = next_versioned_path(copied, always_version=False)
                    shutil.copy2(found, copied)
                    found = copied
            if found and found.exists():
                if not inside(found, work_dir):
                    copied = work_dir / safe_filename(found.name, "downloaded-video")
                    if copied.exists():
                        copied = next_versioned_path(copied, always_version=False)
                    shutil.copy2(found, copied)
                    found = copied
                self._append_log(job, f"URL import produced media file: {found}\n")
                return found.resolve()
            errors.append(f"{label}: completed but no media file was found in {work_dir}")
            self._append_log(job, f"{label} completed but no supported media file was found in {work_dir}.\n")
        self._append_log(job, "\nURL import failed after all candidates. Summary: " + " | ".join(errors[-8:]) + "\n")
        raise RuntimeError("URL import failed. " + " | ".join(errors[-4:]))

    def _archive_uploaded_video_source(self, job: Job, payload: dict[str, Any]) -> None:
        src = safe_existing_path(str(payload.get("uploaded_path", "")), [VIDEO_UPLOAD_DIR, VIDEO_SOURCE_DIR, VIDEO_INTAKE_DIR])
        self._set(job, status="running", started_at=now(), engine="video-intake", role=src.stem, text=f"Save uploaded source media: {src.name}", source_path=str(src))
        if src.suffix.lower() not in MEDIA_EXTS:
            raise ValueError("Selected source is not a supported audio/video file.")
        write_video_source_sidecar(src, {
            "job_id": job.id,
            "source_type": "upload",
            "original_name": str(payload.get("original_name") or src.name),
            "source_media": str(src),
            "media_type": "audio" if src.suffix.lower() in AUDIO_EXTS else "video",
            "duration_seconds": audio_duration_seconds(src),
            "warning": "Use URL import only for content you own, have permission to download, or that is offered under terms that allow downloading. DRM-protected or access-controlled content is not supported.",
        })
        meta = {
            "kind": "video-intake-source",
            "created_at": iso_time(),
            "job_id": job.id,
            "source_type": "upload",
            "source_media": str(src),
            "source_download_url": audio_url_for(src),
            "media_type": "audio" if src.suffix.lower() in AUDIO_EXTS else "video",
            "duration_seconds": audio_duration_seconds(src),
            "archived_only": True,
            "next_step": "Use Extract audio from this source when you want to create a separate audio file.",
        }
        self._append_log(job, f"Saved uploaded source media for archive: {src}\n")
        self._set(job, status="done", result=meta, finished_at=now())

    def _import_video_url_source(self, job: Job, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "").strip()
        slug = video_url_slug(url)
        work_dir = VIDEO_URL_WORK_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_slug(slug)}_{job.id[:8]}"
        self._set(job, status="running", started_at=now(), engine="video-intake", role=slug, text=f"Import URL source media for archive: {url}", source_path=url)
        try:
            src = self._download_video_url(job, url, work_dir)
        except Exception:
            if self._is_cancel_requested(job):
                self._mark_canceled(job)
                return
            raise
        if src.suffix.lower() not in MEDIA_EXTS:
            raise ValueError("URL import did not produce a supported audio/video file.")
        write_video_source_sidecar(src, {
            "job_id": job.id,
            "source_type": "url",
            "source_url": url,
            "source_media": str(src),
            "media_type": "audio" if src.suffix.lower() in AUDIO_EXTS else "video",
            "duration_seconds": audio_duration_seconds(src),
            "warning": "Use URL import only for content you own, have permission to download, or that is offered under terms that allow downloading. DRM-protected or access-controlled content is not supported.",
        })
        meta = {
            "kind": "video-intake-source",
            "created_at": iso_time(),
            "job_id": job.id,
            "source_type": "url",
            "source_url": url,
            "source_media": str(src),
            "source_download_url": audio_url_for(src),
            "media_type": "audio" if src.suffix.lower() in AUDIO_EXTS else "video",
            "duration_seconds": audio_duration_seconds(src),
            "archived_only": True,
            "next_step": "Use Extract audio from this source when you want to create a separate audio file.",
        }
        self._set(job, status="done", result=meta, finished_at=now())

    def _extract_audio_from_video_source(self, job: Job, payload: dict[str, Any]) -> None:
        src = safe_existing_path(str(payload.get("source_path") or payload.get("uploaded_path") or ""), [VIDEO_SOURCE_DIR, VIDEO_UPLOAD_DIR, VIDEO_URL_WORK_DIR, VIDEO_INTAKE_DIR])
        self._set(job, status="running", started_at=now(), engine="video-intake", role=src.stem, text=f"Extract audio from archived source: {src.name}", source_path=str(src))
        if src.suffix.lower() not in MEDIA_EXTS:
            raise ValueError("Selected source is not a supported audio/video file.")
        source_meta = read_output_sidecar(src)
        source_type = str(source_meta.get("source_type") or payload.get("source_type") or ("url" if source_meta.get("source_url") else "archive")).strip().lower()
        source_url = str(source_meta.get("source_url") or payload.get("url") or "").strip()
        fmt_choice = str(payload.get("format") or "wav").lower().strip()
        fmt = video_intake_output_format(fmt_choice)
        output = video_intake_output_path(
            src,
            fmt,
            custom_text=str(payload.get("name") or "").strip(),
            custom_mode=str(payload.get("name_mode") or "none"),
            date_mode=str(payload.get("date_mode") or "none"),
            version_mode=str(payload.get("version_mode") or "collision"),
            function_mode=str(payload.get("function_mode") or "none"),
            filename_template=str(payload.get("filename_template") or ""),
        )
        start = max(0.0, float(payload.get("trim_start") or 0.0))
        dur_raw = str(payload.get("trim_duration") or "").strip()
        duration = max(0.0, float(dur_raw)) if dur_raw else 0.0
        sr_raw = str(payload.get("sample_rate") or "unchanged").strip().lower()
        sample_rate = int(sr_raw) if sr_raw.isdigit() and int(sr_raw) in {16000, 22050, 24000, 44100, 48000} else None
        ch_raw = str(payload.get("channels") or "unchanged").strip().lower()
        channels = 1 if ch_raw in {"1", "mono"} else (2 if ch_raw in {"2", "stereo"} else None)
        mp3_bitrate = str(payload.get("mp3_bitrate") or "192k").strip().lower()
        if mp3_bitrate not in {"96k", "128k", "192k", "256k", "320k"}:
            mp3_bitrate = "192k"
        normalize = bool(payload.get("normalize", True))
        source_wave = audio_lab_waveform_path(src, "video-source")
        create_waveform_svg(src, source_wave)
        cmd = ["ffmpeg", "-y", "-hide_banner"]
        if start > 0:
            cmd += ["-ss", f"{start:g}"]
        cmd += ["-i", str(src)]
        if duration > 0:
            cmd += ["-t", f"{duration:g}"]
        cmd += ["-vn"]
        if normalize:
            cmd += ["-af", "dynaudnorm=f=150:g=15"]
        if sample_rate:
            cmd += ["-ar", str(sample_rate)]
        if channels:
            cmd += ["-ac", str(channels)]
        if fmt == "wav":
            cmd += ["-c:a", "pcm_s16le"]
        elif fmt == "mp3":
            cmd += ["-c:a", "libmp3lame", "-b:a", mp3_bitrate]
        elif fmt == "flac":
            cmd += ["-c:a", "flac"]
        cmd += [str(output)]
        self._set(job, output=str(output), command=cmd)
        rc = self._run_subprocess(job, cmd, cwd=LAB)
        if self._is_cancel_requested(job) or rc in {-15, -9, 143, 137}:
            try:
                if output.exists():
                    output.unlink()
            except Exception:
                pass
            self._mark_canceled(job)
        elif rc == 0 and output.exists():
            ensure_mp3_preview(output, lambda msg: self._append_log(job, msg))
            output_wave = audio_lab_waveform_path(output, "video-audio")
            create_waveform_svg(output, output_wave)
            meta = {
                "kind": "video-intake-output",
                "created_at": iso_time(),
                "job_id": job.id,
                "source_type": source_type,
                "source_url": source_url,
                "source_media": str(src),
                "source_download_url": audio_url_for(src),
                "output_audio": str(output),
                "output_format": fmt,
                "requested_output_format": fmt_choice,
                "trim_start": start,
                "trim_duration": duration,
                "sample_rate": sample_rate or "unchanged",
                "channels": channels or "unchanged",
                "mp3_bitrate": mp3_bitrate if fmt == "mp3" else "",
                "normalize_dynaudnorm": normalize,
                "naming": {
                    "custom_text": str(payload.get("name") or "").strip(),
                    "custom_mode": str(payload.get("name_mode") or "none"),
                    "function_mode": str(payload.get("function_mode") or "none"),
                    "date_mode": str(payload.get("date_mode") or "none"),
                    "version_mode": str(payload.get("version_mode") or "collision"),
                    "filename_template": str(payload.get("filename_template") or ""),
                    "function_label": "extracted",
                },
                "source_waveform": str(source_wave) if source_wave.exists() else "",
                "output_waveform": str(output_wave) if output_wave.exists() else "",
                "warning": "Use URL import only for content you own, have permission to download, or that is offered under terms that allow downloading. DRM-protected or access-controlled content is not supported.",
            }
            output.with_suffix(output.suffix + ".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            self._set(job, status="done", result=meta, finished_at=now())
        else:
            self._set(job, status="error", error=oom_message(rc), finished_at=now())


    def _run_resemble_enhance_job(self, job: Job, payload: dict[str, Any]) -> None:
        mode = str(payload.get("mode") or "enhance").strip().lower()
        if mode not in {"enhance", "denoise"}:
            mode = "enhance"
        function_label = "denoised" if mode == "denoise" else "enhanced"
        device = str(payload.get("device") or "auto").strip().lower()
        if device not in {"auto", "cuda", "cpu"}:
            device = "auto"
        src = safe_existing_path(
            str(payload.get("path") or payload.get("source_path") or ""),
            [REF_DIR, OUT_DIR, PROFILE_DIR, STT_UPLOAD_DIR, RESEMBLE_INPUT_DIR, VIDEO_SOURCE_DIR, VIDEO_EXTRACT_DIR, AUDIO_LAB_DIR],
        )
        if src.suffix.lower() not in AUDIO_EXTS:
            raise ValueError("Selected Resemble Enhance input is not a supported audio file.")
        cmd_base = resemble_best_command()
        if not cmd_base:
            raise RuntimeError("No runnable Resemble Enhance command was detected. Use the Resemble Enhance tab install/repair button first, then refresh status.")
        work_dir = RESEMBLE_OUTPUT_DIR / "work" / job.id
        in_dir = work_dir / "input"
        raw_out_dir = work_dir / "raw_output"
        in_dir.mkdir(parents=True, exist_ok=True)
        raw_out_dir.mkdir(parents=True, exist_ok=True)
        # Resemble Enhance CLI scans its input directory for .wav files only.
        # Preserve the original source, but stage a WAV copy for runtime so MP3/FLAC/M4A/etc. work from the UI.
        staged_input = in_dir / safe_filename(src.stem + ".wav", "input.wav")
        self._set(
            job,
            status="running",
            started_at=now(),
            engine="resemble-enhance",
            role=function_label,
            text=f"{function_label} speech: {src.name}",
            source_path=str(src),
        )
        self._append_log(job, "Resemble Enhance runtime test bench. This is intentionally isolated from Audio Lab.\n")
        self._append_log(job, "Resemble Enhance scans for .wav files. The Web UI stages a normalized temporary PCM WAV input before running it; your original source is left unchanged.\n")
        source_duration = audio_duration_seconds(src)
        source_label = str(payload.get("source_label") or src.name).strip()
        self._append_log(job, f"Selected source at click time: {source_label}\n")
        if source_duration:
            self._append_log(job, f"Detected source duration: {fmt_seconds(source_duration)} ({source_duration:.2f} seconds)\n")
        if mode == "enhance" and source_duration and source_duration > 60:
            self._append_log(job, "WARNING: Enhance mode is VRAM-heavy on long files. On smaller GPUs, try a short clip first or use CPU for isolation.\n")
        if src.suffix.lower() == ".wav":
            self._append_log(job, f"Source is already WAV; normalizing to staged PCM WAV to avoid torchaudio/codec edge cases: {staged_input}\n")
        else:
            self._append_log(job, f"Source is {src.suffix.lower() or 'unknown'}; converting to staged PCM WAV: {staged_input}\n")
        convert_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le", str(staged_input)]
        rc_convert = self._run_subprocess(job, convert_cmd, cwd=LAB)
        if self._is_cancel_requested(job) or rc_convert in {-15, -9, 143, 137}:
            self._mark_canceled(job)
            return
        if rc_convert != 0 or not staged_input.exists() or staged_input.stat().st_size <= 0:
            self._set(job, status="error", error="Could not stage Resemble input as normalized PCM WAV. See job log for ffmpeg details.", result={"mode": mode, "source_audio": str(src), "work_dir": str(work_dir), "staged_input": str(staged_input)}, finished_at=now())
            return
        self._append_log(job, f"Mode: {mode}\nFunction label: {function_label}\nDevice: {device}\nSource: {src}\nStaged input: {staged_input}\nWork directory: {work_dir}\nRaw output directory: {raw_out_dir}\n")
        self._append_log(job, "Detected command: " + shlex.join(cmd_base) + "\n")
        if cmd_base and Path(str(cmd_base[0])).name == "resemble-enhance-webui":
            self._append_log(job, "Using Web UI direct runner/compatibility launcher for better diagnostics. It avoids torchaudio file load/save calls without editing the installed package.\n")
        self._append_log(job, "\n")
        cmd = list(cmd_base) + [str(in_dir), str(raw_out_dir)]
        cmd += ["--device", device]
        if mode == "denoise":
            cmd += ["--denoise_only"]
        self._set(job, command=cmd)
        rc = self._run_subprocess(job, cmd, cwd=LAB)
        if self._is_cancel_requested(job) or rc in {-15, -9, 143, 137}:
            self._mark_canceled(job)
            return
        self._append_log(job, "\nRaw output directory listing after run:\n" + short_dir_listing(raw_out_dir) + "\n")
        self._append_log(job, "\nWork directory listing after run:\n" + short_dir_listing(work_dir) + "\n")
        candidates = [p for p in raw_out_dir.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS and not p.name.endswith(".preview.mp3")]
        candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        if rc != 0:
            git_lfs = resemble_git_lfs_status()
            err = oom_message(rc)
            if not git_lfs.get("available"):
                err = "Resemble model download dependency missing: Git LFS is not available to the isolated Resemble runtime. Open Maintenance → Resemble Enhance and run Install/repair Git LFS, then try again."
            self._set(job, status="error", error=err, result={"mode": mode, "work_dir": str(work_dir), "raw_output_dir": str(raw_out_dir), "git_lfs": git_lfs}, finished_at=now())
            return
        if not candidates:
            self._set(job, status="error", error="Resemble Enhance finished but no output audio file was found. See the job log and raw output directory listing.", result={"mode": mode, "work_dir": str(work_dir), "raw_output_dir": str(raw_out_dir)}, finished_at=now())
            return
        raw_output = candidates[0]
        fmt = raw_output.suffix.lower().lstrip(".") or "wav"
        final_output = resemble_output_path(
            src,
            fmt,
            custom_text=str(payload.get("name") or "").strip(),
            custom_mode=str(payload.get("name_mode") or "none"),
            date_mode=str(payload.get("date_mode") or "none"),
            version_mode=str(payload.get("version_mode") or "collision"),
            function_mode=str(payload.get("function_mode") or "none"),
            filename_template=str(payload.get("filename_template") or ""),
            function_label=function_label,
        )
        if raw_output.resolve() != final_output.resolve():
            final_output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(raw_output, final_output)
        ensure_mp3_preview(final_output, lambda msg: self._append_log(job, msg))
        meta = {
            "kind": "resemble-enhance-output",
            "created_at": iso_time(),
            "job_id": job.id,
            "engine": "resemble-enhance",
            "mode": mode,
            "function_label": function_label,
            "device": device,
            "source_audio": str(src),
            "source_label": source_label,
            "source_duration_seconds": source_duration,
            "staged_input": str(staged_input),
            "raw_output": str(raw_output),
            "output_audio": str(final_output),
            "output_format": fmt,
            "work_dir": str(work_dir),
            "command": cmd,
            "naming": {
                "custom_text": str(payload.get("name") or "").strip(),
                "custom_mode": str(payload.get("name_mode") or "none"),
                "function_mode": str(payload.get("function_mode") or "none"),
                "date_mode": str(payload.get("date_mode") or "none"),
                "version_mode": str(payload.get("version_mode") or "collision"),
                "filename_template": str(payload.get("filename_template") or ""),
                "function_label": function_label,
            },
            "note": "Created by the isolated Resemble Enhance tab. Audio Lab integration remains intentionally disabled.",
        }
        final_output.with_suffix(final_output.suffix + ".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self._set(job, status="done", output=str(final_output), result=meta, finished_at=now())

    def _run_video_intake(self, job: Job, payload: dict[str, Any]) -> None:
        action = str(payload.get("action") or "").strip().lower()
        source_type = str(payload.get("source_type") or "upload").strip().lower()
        if action == "extract" or payload.get("source_path"):
            self._extract_audio_from_video_source(job, payload)
        elif action == "import_url" or source_type == "url":
            self._import_video_url_source(job, payload)
        else:
            self._archive_uploaded_video_source(job, payload)

    def _run_batch(self, job: Job, payload: dict[str, Any]) -> None:
        script = str(payload.get("script", ""))
        role_map = payload.get("role_map") or {}
        if not isinstance(role_map, dict):
            raise ValueError("role_map must be an object.")
        default_engine = str(payload.get("default_engine", "chatterbox")).lower()
        default_ref = str(payload.get("default_ref", str(DEFAULT_REF)))
        default_ref_text = str(payload.get("default_ref_text", ""))
        default_x_vector = bool(payload.get("default_x_vector_only", True))

        lines: list[tuple[str, str]] = []
        for raw in script.splitlines():
            match = ROLE_LINE.match(raw)
            if not match:
                continue
            role, text = match.group(1).strip(), match.group(2).strip()
            if text:
                lines.append((role, text))
        if not lines:
            raise ValueError("No tagged lines found. Use ROLE: dialogue")

        batch_id = uuid.uuid4().hex[:8]
        batch_dir = OUT_DIR / f"batch_{time.strftime('%Y%m%d_%H%M%S')}_{batch_id}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = batch_dir / "manifest.json"

        self._set(job, status="running", started_at=now(), manifest=str(manifest_path))
        manifest: list[dict[str, Any]] = []
        for idx, (role, text) in enumerate(lines, start=1):
            if self._is_cancel_requested(job):
                self._mark_canceled(job)
                return
            cfg = role_map.get(role) or role_map.get(role.upper()) or role_map.get(role.lower()) or {}
            if not isinstance(cfg, dict):
                cfg = {}
            profile_slug = str(cfg.get("profile", "")).strip()
            profile = profile_manifest(PROFILE_DIR / profile_slug) if profile_slug else None
            engine = str(cfg.get("engine", default_engine)).lower()
            ref = str(cfg.get("ref") or (profile or {}).get("audio_path") or default_ref)
            ref_text = str(cfg.get("ref_text") or (profile or {}).get("transcript") or default_ref_text)
            x_vector_only = bool(cfg.get("x_vector_only", default_x_vector))
            output = batch_dir / f"{idx:03d}_{safe_slug(role)}_{engine}.wav"
            line_payload = {
                "engine": engine,
                "role": role,
                "text": text,
                "ref": ref,
                "ref_text": ref_text,
                "x_vector_only": x_vector_only,
                "profile": profile_slug,
            }
            self._append_log(job, f"\n=== {idx:03d} {role} via {engine} ===\n")
            chunks = split_synthesis_text(text)
            if engine == "chatterbox" and bool(line_payload.get("split_on_sentences", True)) and len(chunks) > 1:
                rc = self._run_chunked(job, line_payload, output, chunks)
            else:
                cmd = self._build_command(line_payload, output)
                rc = self._run_subprocess(job, cmd)
            ok = rc == 0 and output.exists()
            if ok:
                self._normalize_wav_for_browser(job, output)
                write_output_sidecar(output, line_payload, job, role=role)
                cooldown = float(os.environ.get("TTS_WEBUI_COOLDOWN_SECONDS", "2"))
                if cooldown > 0 and idx < len(lines):
                    self._append_log(job, f"Cooling down {cooldown:g}s before next line.\n")
                    time.sleep(cooldown)
            rel = output.relative_to(OUT_DIR)
            item = {
                "index": idx,
                "role": role,
                "engine": engine,
                "profile": profile_slug,
                "text": text,
                "output": str(output),
                "audio_url": preview_url_for(output) if output.exists() else "",
                "preview_url": preview_url_for(output) if output.exists() else "",
                "wav_url": audio_url_for(output) if output.exists() else "",
                "returncode": rc,
                "ok": ok,
            }
            manifest.append(item)
            self._set(job, children=manifest.copy())
            if self._is_cancel_requested(job) or rc in {-15, -9, 143, 137}:
                self._mark_canceled(job, f"Canceled by user at line {idx} ({role}).")
                break
            if rc != 0:
                self._set(job, status="error", error=f"Batch stopped at line {idx} ({role}); {oom_message(rc)}")
                break
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if all(item["ok"] for item in manifest):
            self._set(job, status="done", finished_at=now())
        else:
            self._set(job, finished_at=now())


JOBS = JobManager()

INDEX_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>TTS Lab Unified Web UI</title>
<style>
:root { color-scheme: dark; --bg:#101217; --panel:#181c25; --panel2:#11151d; --muted:#9aa4b2; --text:#eef3fb; --accent:#75b7ff; --bad:#ff7676; --ok:#73d18c; --warn:#ffd166; --line:#2a2f3a; --ops-width:560px; }
* { box-sizing: border-box; }
body { margin:0; font-family: system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); overflow:hidden; }
header { padding: 16px 24px; border-bottom: 1px solid var(--line); background: var(--panel2); min-height:76px; }
h1 { margin: 0 0 6px; font-size: 24px; }
main { display:grid; grid-template-columns: minmax(320px, var(--ops-width, 560px)) minmax(320px, 1fr); gap: 18px; padding: 18px; height: calc(100vh - 76px); overflow:hidden; }
body.layout-stack main { display:flex; flex-direction:column; }
body.layout-stack .left-panel { flex: 0 0 min(62vh, 680px); }
body.layout-stack .right-panel { flex: 1 1 320px; }
body.jobs-as-tab .right-panel { display:none; }
body.jobs-as-tab main { grid-template-columns: 1fr; }
body.jobs-as-tab.layout-stack .left-panel { flex: 1 1 auto; }
.jobs-tab-button.hidden { display:none; }
.layout-status { margin-top:6px; min-height:1.2em; }
section { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; box-shadow: 0 8px 22px rgba(0,0,0,.18); overflow-y:auto; min-height:0; }
.sticky-actions { position: sticky; bottom: -16px; background: linear-gradient(180deg, rgba(24,28,37,0.75), var(--panel) 35%); padding: 12px 0 2px; z-index: 5; }
.sticky-top { position: sticky; top: -16px; background: var(--panel); padding: 0 0 10px; z-index: 4; }
.meta-panel { border:1px solid #303747; border-radius:10px; padding:10px; margin:8px 0; background:#11151d; }
label { display:block; margin: 12px 0 6px; color: var(--muted); font-size: 13px; }
input, select, textarea, button { width:100%; border-radius: 10px; border: 1px solid #333b4a; background:#0f131a; color:var(--text); padding:10px; font: inherit; }
input[type="checkbox"] { width:auto; }
textarea { min-height: 120px; resize: vertical; }
button { cursor:pointer; background:#1c5f9f; border-color:#2876c0; font-weight:700; }
button.secondary { background:#242b38; border-color:#384253; }
button.danger { background:#653032; border-color:#8e4b4d; }
button.mini { width:auto; padding:5px 8px; font-size:12px; font-weight:650; display:inline-block; margin:2px; }
button:hover { filter: brightness(1.08); }
.row { display:grid; grid-template-columns: 1fr 1fr; gap:10px; }
.row3 { display:grid; grid-template-columns: 1fr 1fr 1fr; gap:10px; }
.small { color:var(--muted); font-size:13px; line-height:1.45; }
.bad { color:var(--bad); } .ok { color:var(--ok); } .warn { color:var(--warn); }
.tabs { display:flex; gap:8px; margin-bottom: 12px; flex-wrap:wrap; }
.tabs.sticky-tabs { position: sticky; top: -16px; z-index: 7; background: var(--panel); padding: 0 0 10px; border-bottom: 1px solid var(--line); }
.tabs button { width:auto; padding:8px 12px; background:#242b38; }
.tabs button.active { background:#1c5f9f; }
.hidden { display:none; }
.pref-hidden { display:none !important; }
.inline-tools { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.inline-tools button { width:auto; }
.actions-menu { display:inline-block; position:relative; margin:4px 0; }
.actions-menu summary { list-style:none; width:auto; display:inline-block; padding:5px 10px; border-radius:10px; border:1px solid #384253; background:#242b38; color:var(--text); cursor:pointer; font-size:12px; font-weight:700; }
.actions-menu summary::-webkit-details-marker { display:none; }
.actions-menu[open] summary { background:#1c5f9f; border-color:#2876c0; }
.actions-menu-panel { position:absolute; z-index:40; min-width:240px; max-width:340px; margin-top:4px; padding:8px; border:1px solid #384253; border-radius:12px; background:#111722; box-shadow:0 12px 30px rgba(0,0,0,.42); }
.actions-menu-panel button, .actions-menu-panel a { display:block; width:100%; text-align:left; margin:2px 0; padding:7px 8px; border-radius:8px; font-size:12px; }
.actions-menu-panel a { border:1px solid #384253; background:#242b38; color:var(--text); text-decoration:none; font-weight:650; }
.actions-menu-section { color:var(--muted); font-size:11px; font-weight:800; letter-spacing:.04em; text-transform:uppercase; padding:7px 4px 3px; }
.actions-menu-status { display:inline-block; margin-left:8px; min-height:1.2em; }
.output .actions-menu-panel, .job .actions-menu-panel { left:0; }
@media (max-width: 950px) { .actions-menu-panel { position:static; max-width:none; } }
.input-with-buttons { display:grid; grid-template-columns: 1fr auto; gap:6px; align-items:end; }
.option-grid { display:grid; grid-template-columns: 1fr 1fr; gap:8px 16px; }
.option-grid label { margin: 4px 0; }
.card, .job, .output { border-top:1px solid #303747; padding:12px 0; }
.card:first-child, .job:first-child, .output:first-child { border-top:0; }
pre { white-space: pre-wrap; background:#0d1016; border:1px solid #2b3340; border-radius:10px; padding:10px; max-height:260px; overflow:auto; }
.logbox { width:100%; min-height:360px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space:pre; overflow:auto; }
.logtools { display:flex; gap:8px; flex-wrap:wrap; margin:8px 0; }
.logtools button { width:auto; }
.diagbox { width:100%; min-height:150px; max-height:260px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space:pre; overflow:auto; }
.diag-summary { cursor:pointer; font-weight:700; }
.copy-ok { border-color:#4fa96b !important; background:#1f5c34 !important; }
.inline-status { margin:6px 0; min-height:1.2em; }
code { color:#d8e8ff; }
a { color: var(--accent); }
audio { width: 100%; margin: 6px 0; }
.waveforms { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:8px 0; }
.waveform-card { border:1px solid #303747; background:#0f131a; border-radius:10px; padding:8px; }
.waveform-card img { width:100%; display:block; border-radius:8px; background:#0d1016; }
@media (max-width: 950px) { .waveforms { grid-template-columns:1fr; } }
.pill { display:inline-block; padding:2px 8px; border-radius:999px; background:#2a3140; color:var(--muted); font-size:12px; }
.warning-box { border:1px solid #6e5a22; background:#211c12; padding:10px; border-radius:10px; color:#ffe3a1; margin:10px 0; }
.notice-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
.notice-head .notice-title { font-weight:700; }
.notice-actions { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
.maintenance-item { border:1px solid #303747; background:#111722; border-radius:10px; padding:10px; margin:10px 0; }
.maintenance-item h3 { margin-top:0; }
.maintenance-status { margin-top:6px; }
hr { border:0; border-top:1px solid #303747; margin:12px 0; }
@media (max-width: 950px) { body { overflow:auto; } main { grid-template-columns:1fr; height:auto; overflow:visible; } body.layout-stack main { display:block; } body.layout-stack .left-panel, body.layout-stack .right-panel { flex:auto; } section { overflow:visible; } }
</style>
</head>
<body>
<header>
  <h1>TTS Lab Unified Web UI <span id="versionPill" class="pill">v0.78</span></h1>
  <div class="small">Voice profiles, STT transcription, Video Intake archiving/extraction, abortable jobs, Audio Lab processing with waveform previews, Resemble Enhance setup/testing, inline playback, ZIP import/export, and one-at-a-time synthesis for the 6GB GPU.</div>
</header>
<main>
  <section class="left-panel">
    <div class="tabs">
      <button id="tab-single" class="active" onclick="showTab('single')">Synthesize</button>
      <button id="tab-batch" onclick="showTab('batch')">Tagged script</button>
      <button id="tab-profiles" onclick="showTab('profiles')">Profiles</button>
      <button id="tab-refs" onclick="showTab('refs')">Loose files</button>
      <button id="tab-options" onclick="showTab('options')">Options</button>
      <button id="tab-stt" onclick="showTab('stt')">STT / Transcribe</button>
      <button id="tab-video" onclick="showTab('video')">Video Intake</button>
      <button id="tab-audio" onclick="showTab('audio')">Audio Lab</button>
      <button id="tab-resemble" onclick="showTab('resemble')">Resemble Enhance</button>
      <button id="tab-maintenance" onclick="showTab('maintenance')">Maintenance</button>
      <button id="tab-jobs" class="jobs-tab-button hidden" onclick="showTab('jobs')">Jobs</button>
    </div>

    <div id="pane-single">
      <label>Engine</label>
      <select id="engine"></select>
      <div id="engineNote" class="small"></div>
      <label>Voice profile</label>
      <select id="profileSelect" onchange="applySelectedProfile()"></select>
      <div class="small">Choose a saved profile or use manual reference fields below.</div>
      <div class="row">
        <div><label>Role/name for output</label><input id="role" value="EXEC" /></div>
        <div>
          <label>Reference audio path</label>
          <div class="input-with-buttons">
            <input id="ref" />
            <button class="mini secondary" type="button" onclick="chooseSynthRefUpload()">Upload audio</button>
          </div>
          <input id="synthRefUpload" class="hidden" type="file" accept="audio/*" onchange="uploadSynthRef()" />
          <div id="synthRefUploadStatus" class="small"></div>
        </div>
      </div>
      <label>Reference transcript / prompt text</label>
      <textarea id="refText" placeholder="Transcript of the reference voice clip, if known."></textarea>
      <div class="row pref-metadata">
        <button class="secondary" onclick="copyField('refText', this, 'Reference transcript copied.')">Copy reference text</button>
        <button class="secondary" onclick="copyField('ref', this, 'Reference path copied.')">Copy reference path</button>
      </div>
      <div class="small">Manual reference fields are temporary until saved. Use the button below to make original human reference audio a reusable profile.</div>
      <button class="secondary pref-profile-tools" onclick="saveCurrentReferenceProfile()" style="margin-top:8px">Save current reference as voice profile</button>
      <div id="synthProfileStatus" class="small"></div>
      <label><input id="rememberForm" type="checkbox" checked /> Remember this Synthesize form across refreshes and installs</label>
      <button class="mini secondary" onclick="clearRememberedForm()">clear remembered form</button>
      <label class="pref-advanced"><input id="xVector" type="checkbox" checked /> Qwen3 x-vector-only mode</label>
      <label class="pref-advanced"><input id="splitLong" type="checkbox" checked /> Split Chatterbox multi-sentence text into chunks and concatenate</label>
      <label>Text to synthesize</label>
      <textarea id="text" placeholder="Your line here."></textarea>
      <div class="sticky-actions"><button onclick="generateSingle()">Generate</button></div>
    </div>

    <div id="pane-batch" class="hidden">
      <p class="small">Paste dialogue as <code>ROLE: line</code>. Role-map entries can use <code>profile</code> slugs so you do not hardcode paths.</p>
      <label>Tagged script</label>
      <textarea id="script" style="min-height:220px">EXEC: Tucker, status.
TUCKER: The logs say three engines work and one is pretending to be a software landmine.
ANALYST: I can provide fourteen implementation paths.
EXEC: Pick one.</textarea>
      <label>Default engine</label>
      <select id="defaultEngine"></select>
      <label>Role map JSON</label>
      <textarea id="roleMap" style="min-height:180px"></textarea>
      <div class="sticky-actions"><button onclick="generateBatch()">Generate tagged script</button></div>
    </div>

    <div id="pane-profiles" class="hidden">
      <h2>Create voice profile</h2>
      <div id="profileActionStatus" class="small inline-status"></div>
      <div id="pendingProfileBox" class="warning-box hidden"></div>
      <div id="notice-profile-best-path" class="warning-box dismissible-notice" data-notice-id="profile_best_path">
        <div class="notice-head">
          <div><span class="notice-title">Best path.</span> Save a clean original human reference clip with a hand-corrected transcript. Generated audio can be promoted only as an explicit experimental choice because clone-of-clone artifacts can compound.</div>
          <button class="mini secondary" type="button" onclick="dismissNotice('profile_best_path')">dismiss</button>
        </div>
      </div>
      <label>Profile name</label><input id="profileName" placeholder="Chris - Dry Executive" />
      <div class="row">
        <div><label>Speaker</label><input id="profileSpeaker" placeholder="Chris" /></div>
        <div><label>Style</label><input id="profileStyle" placeholder="dry, commanding, podcast voice" /></div>
      </div>
      <label>Reference audio file</label><input id="profileAudioUpload" type="file" accept="audio/*" />
      <label>Reference transcript text</label><textarea id="profileTranscript" placeholder="Paste the transcript of the reference audio here."></textarea>
      <label>Or upload transcript file</label><input id="profileTranscriptUpload" type="file" accept=".txt,.md,.json,text/plain,text/markdown,application/json" />
      <label>Notes</label><textarea id="profileNotes" placeholder="Source, mic, energy, caveats, etc." style="min-height:70px"></textarea>
      <button onclick="createProfileFromForm()">Create profile</button>
      <hr>
      <h2>Import portable profile ZIP</h2>
      <input id="profileZipUpload" type="file" accept=".zip,application/zip" />
      <button onclick="importProfileZip()" style="margin-top:8px">Import ZIP</button>
      <hr>
      <button class="secondary" onclick="loadAll()">Refresh profile library</button>
      <div id="profilesList"></div>
    </div>

    <div id="pane-refs" class="hidden">
      <h2>Loose reference files</h2>
      <div id="refsActionStatus" class="small inline-status"></div>
      <p class="small">This is the old flat reference folder. Profiles are preferred because they pair audio and transcript.</p>
      <label>Upload loose reference audio to /home/user/tts-lab/references</label>
      <input id="refUpload" type="file" accept="audio/*" />
      <label>Save as filename</label>
      <input id="refUploadName" placeholder="tucker_ref.wav" />
      <label>Optional transcript text saved as matching .txt</label>
      <textarea id="refUploadTranscript" placeholder="Transcript for this loose reference."></textarea>
      <button onclick="uploadRef()">Upload loose reference</button>
      <button class="secondary" onclick="loadRefs()" style="margin-top:8px">Refresh loose references</button>
      <div id="refsList" class="small"></div>
    </div>

    <div id="pane-video" class="hidden">
      <h2>Video Intake / Archive / Extract Audio</h2>
      <p class="small">Bring video or permitted page URLs into the local workflow. v0.66 saves source media first for archival purposes, keeps audio extraction separate, writes detailed URL-import diagnostics into the job log, and provides extraction buttons near both the source picker and the bottom of the options panel. Extracted audio is saved under <code>/home/user/tts-lab/output/video_intake/extracted_audio/</code>.</p>
      <div id="notice-video-permitted-use" class="warning-box dismissible-notice" data-notice-id="video_permitted_use">
        <div class="notice-head">
          <div><span class="notice-title">Permitted-use reminder.</span> Use Video Intake only for content you own, have permission to download, or that is offered under terms that allow downloading. DRM-protected or access-controlled content is not supported.</div>
          <button class="mini secondary" type="button" onclick="dismissNotice('video_permitted_use')">dismiss</button>
        </div>
      </div>
      <div id="videoIntakeStatus" class="small">Checking video intake helpers...</div>
      <h3>1. Save source media</h3>
      <div class="row">
        <div>
          <label>Upload video/audio file</label>
          <input id="videoUpload" type="file" accept="video/*,audio/*,.mp4,.mov,.mkv,.webm,.avi,.m4v,.mpg,.mpeg,.wmv,.flv,.mp3,.wav,.flac,.m4a,.ogg,.opus" />
        </div>
        <div>
          <label>Save uploaded source as</label>
          <input id="videoUploadName" placeholder="source-video.mp4" />
        </div>
      </div>
      <button class="secondary" onclick="uploadVideoSource()">Upload and save source</button>
      <hr>
      <label>Import/download from URL</label>
      <input id="videoUrl" placeholder="https://example.com/video-page" />
      <button class="secondary" onclick="importVideoUrl()" style="margin-top:8px">Import URL and save source</button>
      <p class="small">URL import/download no longer auto-extracts audio. When the source is saved, use the job card or the source picker below to extract audio.</p>
      <hr>
      <h3>2. Extract audio from saved source</h3>
      <div class="row">
        <div>
          <label>Archived source media</label>
          <select id="videoSourceSelect" onchange="selectVideoSource()"></select>
          <div class="small"><code id="videoSourcePath"></code></div>
        </div>
        <div>
          <label>&nbsp;</label>
          <button class="mini secondary" onclick="loadVideoSources()">refresh sources</button>
          <button class="mini secondary" onclick="extractSelectedVideoSource()">Extract audio from selected source</button>
        </div>
      </div>
      <h3>Audio extraction options</h3>
      <div class="small naming-summary">File naming uses <b>Options → File naming defaults</b>: <span id="videoNamingSummary"></span></div>
      <div class="row3">
        <div><label>Output format</label><select id="videoFormat" onchange="toggleVideoBitrate()"><option value="wav" selected>WAV - engine-safe reference</option><option value="mp3">MP3 - compact preview/export</option><option value="flac">FLAC - lossless archive</option></select></div>
        <div><label>MP3 bitrate</label><select id="videoMp3Bitrate"><option value="96k">96 kbps</option><option value="128k">128 kbps</option><option value="192k" selected>192 kbps</option><option value="256k">256 kbps</option><option value="320k">320 kbps</option></select></div>
        <div></div>
      </div>
      <div class="row3">
        <div><label>Sample rate</label><select id="videoSampleRate"><option value="unchanged" selected>Unchanged</option><option value="16000">16000 - STT / Cosy-safe</option><option value="22050">22050</option><option value="24000">24000 - TTS/reference common</option><option value="44100">44100</option><option value="48000">48000</option></select></div>
        <div><label>Trim start seconds</label><input id="videoTrimStart" type="number" min="0" step="0.1" placeholder="0" /></div>
        <div><label>Trim duration seconds</label><input id="videoTrimDuration" type="number" min="0" step="0.1" placeholder="leave blank for whole source" /></div>
      </div>
      <div class="row3">
        <div><label>Channels</label><select id="videoChannels"><option value="unchanged" selected>Unchanged</option><option value="1">mono</option><option value="2">stereo</option></select></div>
        <div></div><div></div>
      </div>
      <label><input id="videoNormalize" type="checkbox" checked /> Normalize speech level with FFmpeg dynaudnorm</label>
      <div class="sticky-actions">
        <button onclick="extractSelectedVideoSource()">Extract audio from selected saved source</button>
      </div>
      <div id="videoActionStatus" class="small inline-status"></div>
      <p class="small">After extraction, use the job card Actions dropdown to send audio to STT, use it as a Synthesize reference, open it in Audio Lab or Resemble Enhance, save it as a loose reference, create a voice profile, or launch an external app.</p>
    </div>

    <div id="pane-audio" class="hidden">
      <h2>Audio Lab</h2>
      <p class="small">Foundation audio workbench. Convert uploaded/profile/generated audio into WAV, MP3, or FLAC, trim clips, and normalize speech level before sending audio back to Synthesize.</p>
      <div id="notice-audio-short-reference" class="warning-box dismissible-notice" data-notice-id="audio_short_reference">
        <div class="notice-head">
          <div><span class="notice-title">Short-reference advisory.</span> For Qwen/Cosy/F5 testing, start with short matched clips. Cosy has a hard reference-token extraction limit above 30 seconds; F5 remains experimental/back-burnered locally.</div>
          <button class="mini secondary" type="button" onclick="dismissNotice('audio_short_reference')">dismiss</button>
        </div>
      </div>
      <label>Audio source</label>
      <select id="audioLabSource" onchange="selectAudioLabSource()"></select>
      <div class="small"><code id="audioLabSourcePath"></code></div>
      <button class="mini secondary" onclick="loadAudioLabSources()">refresh sources</button>
      <div class="small naming-summary">File naming uses <b>Options → File naming defaults</b>: <span id="audioNamingSummary"></span></div>
      <div class="row3">
        <div><label>Output format</label><select id="audioLabFormat" onchange="toggleAudioLabBitrate()"><option value="unchanged" selected>Unchanged</option><option value="wav">WAV - engine-safe reference</option><option value="mp3">MP3 - compact preview/export</option><option value="flac">FLAC - lossless archive</option></select></div>
        <div><label>MP3 bitrate</label><select id="audioLabMp3Bitrate"><option value="96k">96 kbps</option><option value="128k">128 kbps</option><option value="192k" selected>192 kbps</option><option value="256k">256 kbps</option><option value="320k">320 kbps</option></select></div>
        <div></div>
      </div>
      <div class="row3">
        <div><label>Sample rate</label><select id="audioLabSampleRate"><option value="unchanged" selected>Unchanged</option><option value="16000">16000 - STT / Cosy-safe</option><option value="22050">22050</option><option value="24000">24000 - TTS/reference common</option><option value="44100">44100</option><option value="48000">48000</option></select></div>
        <div><label>Trim start seconds</label><input id="audioLabTrimStart" type="number" min="0" step="0.1" placeholder="0" /></div>
        <div><label>Trim duration seconds</label><input id="audioLabTrimDuration" type="number" min="0" step="0.1" placeholder="12" /></div>
      </div>
      <div class="row3">
        <div><label>Channels</label><select id="audioLabChannels"><option value="unchanged" selected>Unchanged</option><option value="1">mono</option><option value="2">stereo</option></select></div>
        <div></div><div></div>
      </div>
      <label><input id="audioLabNormalize" type="checkbox" checked /> Normalize speech level with FFmpeg dynaudnorm</label>
      <div class="sticky-actions"><button onclick="processAudioLab()">Process audio</button></div>
      <div id="audioLabStatus" class="small inline-status"></div>
      <p class="small">Processed files are saved under <code>/home/user/tts-lab/output/audio_lab/</code>. Completed Audio Lab jobs appear in Jobs with playback, actual-format download, and before/after waveform previews when available.</p>
    </div>

    <div id="pane-resemble" class="hidden">
      <h2>Resemble Enhance</h2>
      <p class="small">Optional AI speech denoise/enhancement workstation. This is deliberately separate from Audio Lab for now so we can install, test, and understand it without mixing it into the trusted cleanup flow.</p>
      <div id="notice-resemble-setup" class="maintenance-item dismissible-notice" data-notice-id="resemble_setup">
        <div class="notice-head">
          <div><span class="notice-title">Resemble setup / detection.</span> This installer/status apparatus is useful while setting up or repairing the isolated Resemble Enhance environment. You can hide it after the command is detected and restore it from Maintenance later.</div>
          <button class="mini secondary" type="button" onclick="dismissNotice('resemble_setup')">dismiss setup/status</button>
        </div>
        <div id="resembleStatus" class="warning-box">Checking Resemble Enhance status...</div>
        <div class="row">
          <div>
            <label>Install method</label>
            <select id="resembleInstallMode" onchange="scheduleFormStateSave()">
              <option value="auto" selected>auto: conda if available, otherwise venv</option>
              <option value="conda">force conda env</option>
              <option value="venv">force Python venv</option>
            </select>
            <div class="small">Default target: <code>/home/user/tts-lab/engines/resemble-enhance</code>. Conda env name: <code>tts-resemble-enhance</code>.</div>
          </div>
          <div>
            <label>Setup / repair</label>
            <button type="button" onclick="installResembleEnhance()">Install / repair isolated Resemble Enhance environment</button>
            <button class="secondary" type="button" onclick="repairResembleGitLfs()" style="margin-top:8px">Install / repair Git LFS model downloader</button>
            <button class="secondary" type="button" onclick="loadResembleStatus()" style="margin-top:8px">Refresh Resemble status</button>
            <div id="resembleActionStatus" class="small inline-status"></div>
          </div>
        </div>
        <details class="small">
          <summary>What this installer does</summary>
          <p>Creates an isolated environment, upgrades pip tooling, installs <code>resemble-enhance</code>, checks the command, and writes the full install log as a normal abortable Job.</p>
          <p>It does not install Resemble Enhance into the main Web UI environment, and Audio Lab will not use it yet.</p>
        </details>
      </div>
      <hr>
      <h3>Isolated runtime test bench</h3>
      <p class="small">Run Resemble Enhance here only. Audio Lab remains untouched until this engine is understood and trusted locally.</p>
      <div class="row">
        <div>
          <label>Upload audio for Resemble testing</label>
          <input id="resembleUploadFile" type="file" accept="audio/*,.wav,.mp3,.flac,.ogg,.m4a,.aac,.opus" />
        </div>
        <div>
          <label>Save upload as</label>
          <input id="resembleUploadName" placeholder="resemble-test.wav" />
        </div>
      </div>
      <button id="resembleUploadButton" class="secondary" type="button" onclick="uploadResembleInput()">Upload Resemble test audio</button>
      <div id="resembleUploadStatus" class="small inline-status"></div>
      <hr>
      <label>Input audio source</label>
      <select id="resembleSource" onchange="selectResembleSource()"></select>
      <div id="resembleCurrentSource" class="warning-box small">Current Resemble source: <span class="warn">loading sources...</span></div>
      <div><code id="resembleSourcePath"></code></div>
      <button id="resembleRefreshButton" class="mini secondary" type="button" onclick="loadResembleSources()">refresh Resemble sources</button>
      <div class="small naming-summary">File naming uses <b>Options → File naming defaults</b>. Resemble jobs supply <code>[function]</code> as <code>denoised</code> or <code>enhanced</code>.</div>
      <label>Processing device</label>
      <select id="resembleDevice" onchange="scheduleFormStateSave()">
        <option value="auto" selected>auto: GPU if available, otherwise CPU</option>
        <option value="cuda">CUDA / GPU</option>
        <option value="cpu">CPU</option>
      </select>
      <div class="small">If GPU runs out of memory, try CPU for a short clip. Denoise is lighter; Enhance is heavier and may exceed 6 GB VRAM on longer files.</div>
      <div class="row">
        <button id="resembleDenoiseButton" type="button" onclick="runResembleEnhance('denoise')">Denoise only</button>
        <button id="resembleEnhanceButton" type="button" onclick="runResembleEnhance('enhance')">Enhance speech</button>
      </div>
      <div id="resembleRunStatus" class="small inline-status"></div>
      <p class="small">Outputs are saved under <code>/home/user/tts-lab/output/resemble_enhance/</code> and appear in Jobs with playback, download links, handoff buttons, and full logs. Long files may be slow or VRAM-heavy; start with short clips.</p>
    </div>

    <div id="pane-maintenance" class="hidden">
      <h2>Maintenance / Repairs</h2>
      <p class="small">Central place for dismissed notices, diagnostics, setup checks, and repair shortcuts. If a notice has a known fix, the fix should be available here instead of making you restore the notice and hunt for the original tab.</p>
      <div class="row3">
        <button class="secondary" onclick="renderMaintenance()">Refresh maintenance view</button>
        <button class="secondary" onclick="copyDiagnostics(this)">Copy UI diagnostics</button>
        <button class="secondary" onclick="clearDiagnostics()">Clear UI diagnostics</button>
      </div>
      <details id="uiDiagPanel" class="maintenance-item" open>
        <summary class="diag-summary">UI diagnostics / click log <span id="diagCount" class="pill">0</span></summary>
        <div class="small">This records browser-side clicks, handoffs, tab switches, API failures, and JavaScript errors. If a button appears to do nothing, copy this panel and paste it back into the chat.</div>
        <div class="logtools">
          <button class="mini secondary" onclick="copyDiagnostics(this)">copy diagnostics</button>
          <button class="mini secondary" onclick="clearDiagnostics()">clear diagnostics</button>
        </div>
        <textarea id="uiDiagText" class="diagbox" readonly spellcheck="false"></textarea>
      </details>

      <h3>Dismissed notices</h3>
      <div id="dismissedNoticesList" class="small">Loading dismissed notices...</div>

      <h3>Stack status</h3>
      <div class="maintenance-item">
        <h3>TTS Lab stack contract</h3>
        <div class="small">Checks the public-alpha contract without installing anything: Web UI version, lab path, launcher, Conda engine envs, helper tools, video downloader, external launch tools, and log locations.</div>
        <div id="maintStackStatus" class="maintenance-status small">Not checked yet.</div>
        <div class="notice-actions">
          <button class="mini secondary" onclick="maintenanceCheckStack()">Refresh stack status</button>
          <button class="mini secondary" onclick="copyStackDiagnostics(this)">Copy stack diagnostics</button>
        </div>
      </div>

      <h3>Known setup / repair items</h3>
      <div class="maintenance-item">
        <h3>Hugging Face token auth</h3>
        <div class="small">Some model downloads are more reliable with a local read-only Hugging Face token. This is stored locally only.</div>
        <div id="maintHfTokenStatus" class="maintenance-status small">Not checked yet.</div>
        <div class="notice-actions">
          <button class="mini secondary" onclick="maintenanceOpenHfTokenSetup()">Configure token</button>
          <button class="mini secondary" onclick="maintenanceCheckHfToken()">Check status</button>
          <button class="mini secondary" onclick="testHfToken()">Test saved token</button>
        </div>
      </div>

      <div class="maintenance-item">
        <h3>Whisper GPU support</h3>
        <div class="small">CPU fallback can work, but GPU transcription is faster when CUDA/cuDNN dependencies are healthy.</div>
        <div id="maintWhisperStatus" class="maintenance-status small">Not checked yet.</div>
        <div class="notice-actions">
          <button class="mini secondary" onclick="maintenanceOpenWhisperGpuSetup()">Open GPU setup</button>
          <button class="mini secondary" onclick="maintenanceCheckWhisper()">Check STT status</button>
          <button class="mini secondary" onclick="installWhisperCudaSupport()">Install / repair GPU support</button>
          <button class="mini secondary" onclick="testWhisperGpuSupport()">Test GPU support</button>
        </div>
      </div>

      <div class="maintenance-item">
        <h3>Video URL importer</h3>
        <div class="small">Checks whether the web UI can find a runnable URL downloader: <code>/home/user/video-dl</code>, <code>yt-dlp</code>, or <code>TTS_VIDEO_DL_CMD</code>.</div>
        <div id="maintVideoStatus" class="maintenance-status small">Not checked yet.</div>
        <div class="notice-actions">
          <button class="mini secondary" onclick="maintenanceOpenVideoIntake()">Open Video Intake</button>
          <button class="mini secondary" onclick="maintenanceCheckVideoImporter()">Check importer</button>
        </div>
      </div>

      <div class="maintenance-item">
        <h3>Audio Lab short-reference workflow</h3>
        <div class="small">Known fix for the short-reference advisory: use a short 10–20 second clip, usually with a matching transcript for Cosy/Qwen testing.</div>
        <div id="maintAudioShortRefStatus" class="maintenance-status small">Ready.</div>
        <div class="notice-actions">
          <button class="mini secondary" onclick="maintenancePrepareShortReference()">Set Audio Lab for 12-second reference clip</button>
          <button class="mini secondary" onclick="restoreNotice('audio_short_reference')">Restore short-reference notice</button>
        </div>
      </div>

      <div class="maintenance-item">
        <h3>Resemble Enhance</h3>
        <div class="small">Checks the isolated Resemble command and restores the setup/status panel if you need the installer again.</div>
        <div id="maintResembleStatus" class="maintenance-status small">Not checked yet.</div>
        <div class="notice-actions">
          <button class="mini secondary" onclick="showTab('resemble')">Open Resemble Enhance</button>
          <button class="mini secondary" onclick="maintenanceCheckResemble()">Check Resemble status</button>
          <button class="mini secondary" onclick="repairResembleGitLfs()">Install/repair Git LFS</button>
          <button class="mini secondary" onclick="restoreNotice('resemble_setup')">Restore setup/status panel</button>
        </div>
      </div>
    </div>

    <div id="pane-jobs" class="hidden">
      <div id="jobsTabMount"></div>
    </div>

    <div id="pane-options" class="hidden">
      <h2>Options</h2>
      <p class="small">Use these controls to make the lab either full-power or less cluttered. Preferences are saved with the remembered form state under <code>/home/user/tts-lab/config/webui_state.json</code>.</p>
      <label>Interface preset</label>
      <select id="uiMode" onchange="applyModePreset(this.value)">
        <option value="advanced">Show everything</option>
        <option value="producer" selected>Producer default</option>
        <option value="science_fair">Hide the science fair</option>
        <option value="minimal">Minimal</option>
        <option value="custom">Custom</option>
      </select>
      <div class="warning-box">Options hide controls; they do not delete files, profiles, metadata, logs, or remembered form data.</div>
      <p class="small"><b>Show everything</b> exposes every lever. <b>Producer default</b> keeps practical production controls. <b>Hide the science fair</b> hides debugging/experimental controls. <b>Minimal</b> leaves only the basics. Manual checkbox combinations that do not match a preset are shown as <b>Custom</b>.</p>
      <h3>Panel layout</h3>
      <div class="row">
        <div>
          <label>Jobs / Operations orientation</label>
          <select id="optPanelOrientation" onchange="applyLayoutPrefs(); scheduleFormStateSave();">
            <option value="side">Left / right</option>
            <option value="stack">Top / bottom</option>
          </select>
        </div>
        <div>
          <label><input id="optJobsAsTab" type="checkbox" onchange="applyLayoutPrefs(); scheduleFormStateSave();" /> Hide Jobs panel and show Jobs as a tab</label>
          <div class="small">Useful when you want the operation form to use the whole window.</div>
        </div>
      </div>
      <label>Operations panel width: <span id="opsWidthLabel">560px</span></label>
      <input id="optOpsWidth" type="range" min="320" max="900" step="20" value="560" oninput="applyLayoutPrefs(); scheduleFormStateSave();" />
      <div id="layoutStatus" class="small layout-status"></div>
      <h3>File naming defaults</h3>
      <p class="small">These defaults are shared by Audio Lab and Video Intake extraction. Use the simple menus to build a template, or type your own filename pattern directly.</p>
      <div class="row3">
        <div><label>Custom filename text</label><input id="globalName" placeholder="project label, episode name, source tag" oninput="updateNamingSummaries(); scheduleFormStateSave();" /></div>
        <div><label>Apply custom text</label><select id="globalNameMode" onchange="buildFilenameTemplateFromControls();"><option value="none" selected>ignore custom text</option><option value="prefix">custom as prefix</option><option value="suffix">custom as suffix</option><option value="replace">custom as full base filename</option></select></div>
        <div><label>Function file naming</label><select id="globalFunctionMode" onchange="buildFilenameTemplateFromControls();"><option value="none" selected>No Function Naming</option><option value="prefix">Function as Prefix</option><option value="suffix">Function as Suffix</option></select></div>
      </div>
      <div class="row3">
        <div><label>Date stamp</label><select id="globalDateMode" onchange="buildFilenameTemplateFromControls();"><option value="none" selected>no date</option><option value="prefix">YYYYMMDD prefix</option><option value="suffix">YYYYMMDD suffix</option></select></div>
        <div><label>Version suffix</label><select id="globalVersionMode" onchange="updateNamingSummaries(); scheduleFormStateSave();"><option value="collision" selected>only if filename exists</option><option value="always">always append -v1, -v2...</option><option value="none">none; add timestamp only on conflict</option></select></div>
        <div><label>Insert token</label><select id="filenameTokenPicker" onchange="insertFilenameToken(this.value); this.value='';"><option value="">choose token...</option><option value="[source]">[source]</option><option value="[function]">[function]</option><option value="[custom]">[custom]</option><option value="[version]">[version]</option><option value="[.ext]">[.ext]</option><option value="[YYYYMMDD]">[YYYYMMDD]</option><option value="[YYYY-MM-DD]">[YYYY-MM-DD]</option><option value="[year]">[year]</option><option value="[month]">[month]</option><option value="[day]">[day]</option><option value="[weekday]">[weekday]</option><option value="[time24hour]">[time24hour]</option><option value="[time-am-pm]">[time-am-pm]</option><option value="[timestamp]">[timestamp]</option></select></div>
      </div>
      <label>Filename template</label>
      <input id="globalFilenameTemplate" placeholder="[YYYYMMDD]-[source]-[function][version][.ext]" oninput="updateNamingSummaries(); scheduleFormStateSave();" />
      <div class="inline-tools">
        <button class="mini secondary" type="button" onclick="buildFilenameTemplateFromControls()">Update template from menus</button>
        <button class="mini secondary" type="button" onclick="resetGlobalNamingDefaults()">Reset naming defaults</button>
        <button class="mini secondary" type="button" onclick="showTab('audio')">Open Audio Lab</button>
        <button class="mini secondary" type="button" onclick="showTab('video')">Open Video Intake</button>
      </div>
      <div id="globalNamingStatus" class="small layout-status"></div>
      <details class="small">
        <summary>Available filename tokens</summary>
        <p><code>[source]</code> original filename, <code>[function]</code> clean/extracted/etc., <code>[custom]</code> your custom text, <code>[version]</code> -v1 when needed, <code>[.ext]</code> output extension.</p>
        <p>Date/time: <code>[YYYYMMDD]</code>, <code>[YYYY-MM-DD]</code>, <code>[year]</code>, <code>[month]</code>, <code>[day]</code>, <code>[weekday]</code>, <code>[time24hour]</code>, <code>[time-am-pm]</code>, <code>[timestamp]</code>.</p>
      </details>
      <h3>Visible controls</h3>
      <div class="option-grid">
        <label><input id="optAdvanced" type="checkbox" checked onchange="syncPrefsToPreset(); applyUiPrefs(); scheduleFormStateSave();" /> Show advanced engine options</label>
        <label><input id="optProfileTools" type="checkbox" checked onchange="syncPrefsToPreset(); applyUiPrefs(); scheduleFormStateSave();" /> Show profile import/export/save tools</label>
        <label><input id="optExperimental" type="checkbox" onchange="syncPrefsToPreset(); applyUiPrefs(); scheduleFormStateSave();" /> Show generated-output experimental profile tools</label>
        <label><input id="optMetadata" type="checkbox" checked onchange="syncPrefsToPreset(); applyUiPrefs(); scheduleFormStateSave();" /> Show text/metadata/copy helpers</label>
        <label><input id="optLogs" type="checkbox" checked onchange="syncPrefsToPreset(); applyUiPrefs(); scheduleFormStateSave();" /> Show job logs</label>
        <label><input id="optDelete" type="checkbox" checked onchange="syncPrefsToPreset(); applyUiPrefs(); scheduleFormStateSave();" /> Show delete buttons</label>
        <label><input id="optStickyTabs" type="checkbox" onchange="applyUiPrefs(); scheduleFormStateSave();" /> Keep tabs sticky while scrolling</label>
      </div>
    </div>

    <div id="pane-stt" class="hidden">
      <h2>STT / Transcribe</h2>
      <p class="small">First local transcription lane. Use it to draft reference transcripts from uploaded audio, profiles, loose references, or generated outputs. Review/edit before saving.</p>
      <div id="sttStatus" class="warning-box">Checking Faster-Whisper status...</div>
      <div id="hfTokenCompactStatus" class="small"></div>
      <details id="hfTokenSetupBox" class="warning-box small hidden">
        <summary>Hugging Face token / first-download setup</summary>
        <p>Some Whisper models download from Hugging Face. Anonymous downloads can be slower or rate-limited. A free <b>read-only</b> token improves reliability.</p>
        <div id="hfTokenStatus">Checking Hugging Face token status...</div>
        <label>Paste read-only Hugging Face token</label>
        <input id="hfTokenInput" type="password" placeholder="hf_..." autocomplete="off" />
        <div class="inline-tools">
          <button class="mini secondary" onclick="saveHfToken()">Save token locally</button>
          <button class="mini secondary" onclick="testHfToken()">Test saved token</button>
          <button class="mini danger" onclick="forgetHfToken()">Forget token</button>
        </div>
        <p class="small">How to get one: create/log into a Hugging Face account → account settings → Access Tokens → create a <b>read-only</b> token named something like <code>tts-lab-local-readonly</code>. Paste it here only. Do not paste tokens into chats, screenshots, GitHub issues, or public logs.</p>
      </details>
      <details id="whisperGpuSetupBox" class="warning-box small" open>
        <summary>Whisper GPU support / CUDA setup</summary>
        <p>CPU transcription already works through fallback. GPU transcription is optional and faster when the local CUDA runtime libraries are usable.</p>
        <p class="small">If GPU mode complains about <code>libcublas.so.12</code> or cuDNN, Device=auto will try to fall back to CPU. Use Device=cpu to intentionally transcribe on CPU, or install the optional CUDA libraries here.</p>
        <div class="inline-tools">
          <button class="mini secondary" onclick="installWhisperCudaSupport()">Install / repair Whisper GPU support</button>
          <button class="mini secondary" onclick="testWhisperGpuSupport()">Test GPU transcription support</button>
          <button class="mini secondary" onclick="restartWebUi()">Restart Web UI</button>
          <button class="mini secondary" onclick="hideWhisperGpuSetup()">hide GPU setup</button>
        </div>
        <div id="sttMaintenanceStatus" class="small">GPU setup/test jobs appear in Jobs. After a successful test, you can collapse this panel if you do not need the controls.</div>
      </details>
      <div class="row">
        <div>
          <label>Upload audio for transcription</label>
          <input id="sttUpload" type="file" accept="audio/*" />
        </div>
        <div>
          <label>Save as filename</label>
          <input id="sttUploadName" placeholder="voice_sample.wav" />
        </div>
      </div>
      <button class="secondary" onclick="uploadSttAudio()">Upload STT audio</button>
      <div id="sttUploadStatus" class="small"></div>
      <hr>
      <label>Audio source</label>
      <select id="sttSource" onchange="selectSttSource()"></select>
      <div class="small"><code id="sttSourcePath"></code></div>
      <div id="sttSavedTranscriptNotice" class="small"></div>
      <div class="row3">
        <div><label>Whisper model</label><select id="sttModel"><option value="tiny">tiny</option><option value="base" selected>base</option><option value="small">small</option><option value="medium">medium</option></select></div>
        <div><label>Language</label><input id="sttLanguage" placeholder="auto or en" value="auto" /></div>
        <div><label>Device</label><select id="sttDevice"><option value="auto" selected>auto</option><option value="cuda">cuda</option><option value="cpu">cpu</option></select></div>
      </div>
      <label class="pref-advanced">Compute type</label>
      <select id="sttCompute" class="pref-advanced"><option value="auto" selected>auto - safe default</option><option value="int8">int8 - safest CPU</option><option value="float32">float32 - CPU compatible but heavier</option><option value="float16">float16 - GPU only</option></select>
      <button onclick="transcribeStt()">Transcribe selected audio</button>
      <label>Transcript draft / corrected transcript</label>
      <textarea id="sttTranscript" placeholder="Transcription result appears here. Edit before saving or using as reference." style="min-height:180px"></textarea>
      <div class="row3 pref-metadata">
        <button class="secondary" onclick="copyField('sttTranscript', this, 'Transcript copied.')">Copy transcript</button>
        <button class="secondary" onclick="useSttAsSynthesizeReference()">Use audio + transcript as reference</button>
        <button class="secondary" onclick="saveSttTranscript()">Save beside selected audio</button>
      </div>
      <div id="sttActionStatus" class="small inline-status"></div>
      <details class="pref-metadata"><summary>STT metadata / segments</summary><button class="mini secondary" onclick="copyText($('sttMeta').textContent || '', 'STT metadata copied.', this)">copy metadata</button><pre id="sttMeta">No transcription yet.</pre></details>
    </div>
  </section>

  <section class="right-panel">
    <div id="jobsPanelMount">
    <div id="jobsPanelContent">
    <div class="sticky-top">
    <div class="row3">
      <button class="secondary" onclick="refreshJobs()">Refresh jobs</button>
      <button class="secondary" onclick="loadOutputs()">Refresh outputs</button>
      <button class="secondary" onclick="loadAll()">Refresh all</button>
    </div>
    </div>
    <h2>Jobs</h2>
    <div id="activeLogPanel" class="card hidden pref-logs">
      <h3>Job log <span id="activeLogTitle" class="pill"></span></h3>
      <div class="small">Logs open in this stable viewer so auto-refresh cannot collapse them or fight scrolling.</div>
      <div class="logtools">
        <button class="mini secondary" onclick="refreshActiveLog(true)">refresh log</button>
        <button class="mini secondary" onclick="copyActiveLog(this)">copy log</button>
        <button class="mini secondary" onclick="scrollLogBottom()">bottom</button>
        <button class="mini danger" onclick="closeJobLog()">close log</button>
      </div>
      <textarea id="activeLogText" class="logbox" readonly spellcheck="false"></textarea>
    </div>
    <div id="jobs"></div>
    <h2>Recent audio</h2>
    <div class="small">Use as reference is temporary and fills the synthesis form. Experimental promotion creates a saved profile from generated audio only after you confirm the clone-of-clone warning.</div>
    <div id="outputs" class="small"></div>
    </div>
    </div>
  </section>
</main>
<script>
let engines = {};
let profiles = [];
let poll = null;
let lastJobsSig = '';
let lastOutputsSig = '';
let activeLogId = null;
let activeLogTitle = "";
let formStateLoaded = false;
let stateSaveTimer = null;
let currentSttJobId = null;
let lastSttSelectedPath = null;
const TAB_NAMES = ['single','batch','profiles','refs','options','stt','video','audio','resemble','maintenance','jobs'];
let uiDiagEvents = [];
let currentTabName = '';
let lastStackStatus = null;
let pendingProfileSource = null;
let pendingProfileTranscript = '';
let pendingProfileExperimental = false;
let dismissedNotices = new Set();
let hfAuthIssueDetected = false;
let hfTokenSetupManuallyOpened = false;
function $(id){ return document.getElementById(id); }
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function diagValue(v){
  try{
    if(v === undefined || v === null || v === '') return '';
    if(typeof v === 'string') return v.length > 900 ? v.slice(0,900) + '…' : v;
    return JSON.stringify(v, (k,val)=> typeof val === 'string' && val.length > 900 ? val.slice(0,900) + '…' : val);
  } catch(e){ return String(v); }
}
function renderDiagnostics(){
  const box = $('uiDiagText');
  const count = $('diagCount');
  if(count) count.textContent = String(uiDiagEvents.length);
  if(!box) return;
  const nearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 24;
  box.value = uiDiagEvents.join('\n');
  if(nearBottom) box.scrollTop = box.scrollHeight;
}
function logUiEvent(message, data=null, level='info'){
  const t = new Date().toLocaleTimeString();
  const prefix = level === 'error' ? 'ERROR' : (level === 'warn' ? 'WARN' : 'INFO');
  const suffix = data ? ' — ' + diagValue(data) : '';
  uiDiagEvents.push(`[${t}] ${prefix}: ${message}${suffix}`);
  if(uiDiagEvents.length > 250) uiDiagEvents = uiDiagEvents.slice(-250);
  renderDiagnostics();
  try{
    if(level === 'error') console.error('[TTS UI]', message, data);
    else if(level === 'warn') console.warn('[TTS UI]', message, data);
    else console.log('[TTS UI]', message, data || '');
  }catch(e){}
}
function diagnosticsText(){
  return [
    'TTS Lab UI diagnostics',
    'URL: ' + location.href,
    'User agent: ' + navigator.userAgent,
    'Time: ' + new Date().toISOString(),
    'App version: ' + (($('versionPill') && $('versionPill').textContent) || 'unknown'),
    '',
    uiDiagEvents.join('\n') || '(no diagnostic events yet)'
  ].join('\n');
}
function copyDiagnostics(btn){ copyText(diagnosticsText(), 'Diagnostics copied.', btn); }
function clearDiagnostics(){ uiDiagEvents = []; renderDiagnostics(); logUiEvent('diagnostics cleared'); }
window.addEventListener('error', ev=>{ logUiEvent('JavaScript error', {message:ev.message, source:ev.filename, line:ev.lineno, column:ev.colno, stack:ev.error && ev.error.stack}, 'error'); });
window.addEventListener('unhandledrejection', ev=>{ logUiEvent('Unhandled promise rejection', {reason:String(ev.reason && (ev.reason.stack || ev.reason.message || ev.reason))}, 'error'); });
function api(path, opts={}){
  const method = String(opts.method || 'GET').toUpperCase();
  return fetch(path, Object.assign({headers:{'Content-Type':'application/json'}}, opts)).then(async r=>{
    const j=await r.json().catch(()=>({error:'Bad JSON response'}));
    if(!r.ok) throw new Error(j.error || r.statusText);
    if(method !== 'GET') logUiEvent('API success', {method, path});
    return j;
  }).catch(err=>{ logUiEvent('API failure', {method, path, error:String(err && (err.message || err))}, 'error'); throw err; });
}
function fileToB64(file){ return new Promise((resolve,reject)=>{ const r=new FileReader(); r.onerror=()=>reject(r.error); r.onload=()=>resolve(String(r.result).split(',')[1]); r.readAsDataURL(file); }); }
function fileToText(file){ return new Promise((resolve,reject)=>{ const r=new FileReader(); r.onerror=()=>reject(r.error); r.onload=()=>resolve(String(r.result||'')); r.readAsText(file); }); }
function anyAudioPlaying(){ return Array.from(document.querySelectorAll('audio')).some(a => !a.paused && !a.ended); }
function stopPoll(){ if(poll){ clearInterval(poll); poll = null; } }
function showTab(name, updateHash=true){
  if(!TAB_NAMES.includes(name)) name='single';
  const previous = currentTabName;
  for (const p of TAB_NAMES) {
    const pane=$('pane-'+p), tab=$('tab-'+p);
    if(!pane || !tab){ logUiEvent('Missing tab DOM element', {tab:p, pane_exists:!!pane, tab_exists:!!tab}, 'error'); continue; }
    pane.classList.toggle('hidden', p!==name); tab.classList.toggle('active', p===name);
  }
  currentTabName = name;
  if(previous && previous !== name) logUiEvent('tab switch', {from:previous, to:name});
  if(updateHash && location.hash !== '#'+name) history.replaceState(null, '', '#'+name);
}
function restoreTabFromHash(){ const name=(location.hash||'').replace(/^#/, ''); if(TAB_NAMES.includes(name)) showTab(name, false); }
window.addEventListener('hashchange', restoreTabFromHash);
function setupEngines(meta){
  engines = meta.engines; if($('versionPill')) $('versionPill').textContent = 'v' + (meta.version || '0.78'); const selects = [$('engine'), $('defaultEngine')];
  for (const sel of selects) { sel.innerHTML=''; for (const [k,v] of Object.entries(engines)) { const o=document.createElement('option'); o.value=k; o.textContent=v.label + (v.status.includes('broken')?' ⚠':''); sel.appendChild(o); } }
  $('engine').value='chatterbox'; $('defaultEngine').value='qwen3'; $('ref').value=meta.default_ref;
  updateEngineNote();
}
function updateEngineNote(){ const v=engines[$('engine').value]; $('engineNote').innerHTML = v ? `<span class="pill">${esc(v.status)}</span> ${esc(v.note)}` : ''; }
$('engine').addEventListener('change', updateEngineNote);
function renderProfileSelect(){
  const sel = $('profileSelect'); sel.innerHTML='';
  let none = document.createElement('option'); none.value=''; none.textContent='Manual reference fields'; sel.appendChild(none);
  for (const p of profiles) { const o=document.createElement('option'); o.value=p.slug; o.textContent=p.name + (p.style ? ' — '+p.style : ''); sel.appendChild(o); }
}
function applySelectedProfile(){ const slug=$('profileSelect').value; const p=profiles.find(x=>x.slug===slug); if(!p) { scheduleFormStateSave(); return; } $('ref').value=p.audio_path; $('refText').value=p.transcript || ''; $('role').value=p.name || ''; if($('synthRefUploadStatus')) $('synthRefUploadStatus').innerHTML=''; $('synthProfileStatus').innerHTML = '<span class="ok">Selected profile:</span> <b>'+esc(p.name || slug)+'</b><br><span class="small">Role/name was filled from the profile name. You can edit it before generating.</span>'; scheduleFormStateSave(); }
function generateSingle(){
  const profileSlug = $('profileSelect').value;
  const body = {engine:$('engine').value, role:$('role').value, profile:profileSlug, ref:$('ref').value, ref_text:$('refText').value, x_vector_only:$('xVector').checked, split_on_sentences:$('splitLong').checked, text:$('text').value};
  saveFormStateNow();
  api('/api/generate', {method:'POST', body:JSON.stringify(body)}).then(()=>{ lastJobsSig=''; refreshJobs(); startPoll(); }).catch(alert);
}
function generateBatch(){
  let roleMap = {}; try { roleMap = JSON.parse($('roleMap').value || '{}'); } catch(e){ alert('Role map JSON is invalid: '+e); return; }
  const body = {script:$('script').value, role_map:roleMap, default_engine:$('defaultEngine').value, default_ref:$('ref').value, default_ref_text:$('refText').value, default_x_vector_only:true};
  api('/api/batch', {method:'POST', body:JSON.stringify(body)}).then(()=>{ lastJobsSig=''; refreshJobs(); startPoll(); }).catch(alert);
}
function statusClass(s){ return s==='done'?'ok':(s==='error'?'bad':((s==='running'||s==='queued'||s==='canceling')?'warn':(s==='canceled'?'bad':''))); }
function jsStr(s){ return JSON.stringify(String(s ?? '')); }
function fmtDur(sec){ if(sec === null || sec === undefined || Number.isNaN(Number(sec))) return ''; const n=Number(sec); return n < 60 ? `${n.toFixed(1)}s` : `${Math.floor(n/60)}:${String(Math.round(n%60)).padStart(2,'0')}`; }
function fmtDuration(sec){ sec=Number(sec||0); if(!isFinite(sec)||sec<=0) return 'unknown'; if(sec<60) return sec.toFixed(1)+'s'; return Math.floor(sec/60)+':'+String(Math.round(sec%60)).padStart(2,'0'); }
function durationBadge(sec, warn){ const d=fmtDur(sec); if(!d) return ''; return `<span class="pill ${warn?'bad':''}">${d}${warn?' - short ref':''}</span>`; }
function setInlineStatus(id, html){ const el=id ? $(id) : null; if(el) el.innerHTML=html; }
function focusPane(name){ const pane=$('pane-'+name); if(pane) pane.scrollIntoView({block:'start', behavior:'smooth'}); }
function dataAttrs(obj){
  return Object.entries(obj || {}).filter(([k,v]) => v !== undefined && v !== null && String(v) !== '').map(([k,v]) => ` data-${k}="${esc(v)}"`).join('');
}
function actionButton(label, action, opts={}, extraClass='secondary'){
  return `<button type="button" class="mini ${extraClass} action-btn" data-action="${esc(action)}"${dataAttrs(opts)}>${esc(label)}</button>`;
}
function actionLink(label, href, download=false){
  if(!href) return '';
  return `<a class="action-menu-link" href="${esc(href)}" ${download?'download':''}>${esc(label)}</a>`;
}
function actionMenu(label, items=[], key=''){
  const statusId = key ? 'action-menu-status-' + key : '';
  const parts = [];
  for(const item of items){
    if(!item) continue;
    if(item.section){ parts.push(`<div class="actions-menu-section">${esc(item.section)}</div>`); continue; }
    if(item.link){ parts.push(actionLink(item.label || 'download', item.href || '', !!item.download)); continue; }
    parts.push(actionButton(item.label || item.action || 'action', item.action, item.opts || {}, item.extraClass || 'secondary'));
  }
  return `<details class="actions-menu pref-metadata"><summary>${esc(label || 'Actions')} ▾</summary><div class="actions-menu-panel">${parts.join('')}</div></details>${statusId?`<span id="${esc(statusId)}" class="small actions-menu-status inline-status"></span>`:''}`;
}
function outputActions(path, text, key=''){
  if(!path) return '';
  const statusId = key ? 'action-menu-status-' + key : '';
  const transcript = text || '';
  return actionMenu('Actions', [
    {section:'Use in app'},
    {label:'Use as Synthesize reference', action:'set-reference', opts:{path, transcript}},
    {label:'Send to STT', action:'open-stt', opts:{path}},
    {label:'Open in Audio Lab', action:'open-audio-lab', opts:{path}},
    {label:'Open in Resemble Enhance', action:'open-resemble', opts:{path}},
    {label:'Save as reference', action:'save-reference', opts:{path, transcript, statusid: statusId}},
    {label:'Create voice profile', action:'create-profile', opts:{path, transcript}, extraClass:'secondary pref-profile-tools'},
    {label:'Make experimental profile', action:'promote-output', opts:{path}, extraClass:'danger pref-experimental'},
    {section:'Open externally'},
    {label:'Send to Audacity', action:'open-external', opts:{path, target:'audacity', statusid: statusId}},
    {label:'Open with system default app', action:'open-external', opts:{path, target:'system-default', statusid: statusId}},
    {label:'Open containing folder', action:'open-external', opts:{path, target:'containing-folder', statusid: statusId}},
    {section:'Danger'},
    {label:'Delete', action:'delete-output', opts:{path, name:path.split('/').pop()}, extraClass:'danger pref-delete'},
  ], key);
}
function closeActionMenus(except=null){
  document.querySelectorAll('details.actions-menu[open]').forEach(el=>{ if(el !== except) el.removeAttribute('open'); });
}
document.addEventListener('click', function(ev){
  const menuSummary = ev.target.closest ? ev.target.closest('.actions-menu > summary') : null;
  if(menuSummary){ const menu=menuSummary.parentElement; setTimeout(()=>closeActionMenus(menu), 0); return; }
  const actionBtn = ev.target.closest ? ev.target.closest('.action-btn') : null;
  if(actionBtn){
    ev.preventDefault();
    const openMenu = actionBtn.closest ? actionBtn.closest('.actions-menu') : null;
    if(openMenu) openMenu.removeAttribute('open');
    const d = actionBtn.dataset || {};
    const action = d.action || '';
    const path = d.path || '';
    const transcript = d.transcript || d.text || '';
    logUiEvent('clicked action item', {action, label:(actionBtn.textContent||'').trim(), path, target:d.target || '', transcript_chars:transcript.length});
    try{
      switch(action){
        case 'set-reference': setReference(path, transcript); return;
        case 'open-stt': openInStt(path); return;
        case 'open-audio-lab': openInAudioLab(path); return;
        case 'open-resemble': openInResemble(path); return;
        case 'open-external': openExternalTarget(path, d.target || 'system-default', d.statusid || d.statusId || ''); return;
        case 'save-reference': saveAudioAsReference(path, transcript, d.statusid || d.statusId || ''); return;
        case 'create-profile': createProfileFromAudio(path, transcript); return;
        case 'promote-output': promoteOutput(path); return;
        case 'delete-output': deleteOutput(path, d.name || path.split('/').pop()); return;
        case 'extract-video-source': extractVideoSource(path, d.statusid || d.statusId || ''); return;
        default: logUiEvent('Unknown action item', {action, label:(actionBtn.textContent||'').trim(), path}, 'warn'); return;
      }
    } catch(e){
      logUiEvent('Action handler crashed', {action, error:String(e && (e.stack || e.message || e))}, 'error');
      throw e;
    }
  } else if(!(ev.target.closest && ev.target.closest('.actions-menu'))){
    closeActionMenus();
  }
  const btn = ev.target.closest ? ev.target.closest('.view-log-btn') : null;
  if(btn){ ev.preventDefault(); logUiEvent('clicked view job log', {jobid:btn.dataset.jobid || '', title:btn.dataset.title || 'job'}); openJobLog(btn.dataset.jobid || '', btn.dataset.title || 'job'); return; }
  const copyBtn = ev.target.closest ? ev.target.closest('.copy-btn') : null;
  if(copyBtn){ ev.preventDefault(); logUiEvent('clicked copy helper', {message:copyBtn.dataset.copyMessage || 'Copied.'}); copyText(copyBtn.dataset.copy || '', copyBtn.dataset.copyMessage || 'Copied.', copyBtn); return; }
  const sttLoad = ev.target.closest ? ev.target.closest('.stt-load-btn') : null;
  if(sttLoad){ ev.preventDefault(); logUiEvent('clicked STT transcript load', {path:sttLoad.dataset.path || '', text_chars:(sttLoad.dataset.text || '').length}); useSttJobTranscript(sttLoad.dataset.text || '', sttLoad.dataset.path || ''); return; }
  const sttUseRef = ev.target.closest ? ev.target.closest('.stt-use-ref-btn') : null;
  if(sttUseRef){ ev.preventDefault(); logUiEvent('clicked STT use as reference', {path:sttUseRef.dataset.path || '', text_chars:(sttUseRef.dataset.text || '').length}); useSttAsSynthesizeReference(sttUseRef.dataset.path || '', sttUseRef.dataset.text || ''); return; }
  const sttSave = ev.target.closest ? ev.target.closest('.stt-save-btn') : null;
  if(sttSave){ ev.preventDefault(); logUiEvent('clicked STT save transcript', {path:sttSave.dataset.path || '', jobid:sttSave.dataset.jobid || ''}); saveSttJobTranscript(sttSave.dataset.path || '', sttSave.dataset.text || '', sttSave.dataset.jobid || ''); return; }
  const cancelBtn = ev.target.closest ? ev.target.closest('.cancel-job-btn') : null;
  if(cancelBtn){ ev.preventDefault(); logUiEvent('clicked abort job', {jobid:cancelBtn.dataset.jobid || ''}, 'warn'); cancelJob(cancelBtn.dataset.jobid || ''); return; }
});
function openJobLog(id, title){
  activeLogId = id; activeLogTitle = title || id;
  $('activeLogTitle').textContent = activeLogTitle;
  $('activeLogPanel').classList.remove('hidden');
  refreshActiveLog(true);
}
function closeJobLog(){ activeLogId=null; $('activeLogPanel').classList.add('hidden'); $('activeLogText').value=''; }
function scrollLogBottom(){ const box=$('activeLogText'); box.scrollTop = box.scrollHeight; }
function refreshActiveLog(forceBottom=false){
  if(!activeLogId) return Promise.resolve();
  const box = $('activeLogText');
  const oldTop = box.scrollTop;
  const nearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 24;
  return api('/api/jobs/'+activeLogId).then(d=>{
    const job = d.job || {};
    const text = job.log || '(no log saved for this job)';
    if (box.value !== text) box.value = text;
    if(forceBottom || nearBottom) box.scrollTop = box.scrollHeight; else box.scrollTop = oldTop;
  }).catch(err=>{ box.value = 'Could not load log: '+err; });
}
function copyActiveLog(btn){ const text=$('activeLogText').value || ''; copyText(text, 'Log copied to clipboard.', btn); }
function showCopySuccess(sourceEl, message='Copied.'){
  if(sourceEl){
    const el = sourceEl.closest ? (sourceEl.closest('button') || sourceEl) : sourceEl;
    const old = el.dataset.copyOldHtml || el.innerHTML;
    el.dataset.copyOldHtml = old;
    el.classList.add('copy-ok');
    el.innerHTML = '✓';
    clearTimeout(el._copyTimer);
    el._copyTimer = setTimeout(()=>{ el.innerHTML = el.dataset.copyOldHtml || old; el.classList.remove('copy-ok'); }, 1100);
  } else if($('sttActionStatus')) {
    $('sttActionStatus').innerHTML = '<span class="ok">' + esc(message) + '</span>';
    setTimeout(()=>{ if($('sttActionStatus')) $('sttActionStatus').innerHTML=''; }, 1600);
  }
}
function copyText(text, message='Copied to clipboard.', sourceEl=null){
  text = String(text ?? '');
  const ok = () => showCopySuccess(sourceEl, message);
  const fail = (e) => { if($('sttActionStatus')) $('sttActionStatus').innerHTML='<span class="bad">Copy failed: '+esc(e)+'</span>'; else console.warn('Copy failed', e); };
  if(navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(text).then(ok).catch(()=>fallbackCopy(text, ok, fail));
  } else { fallbackCopy(text, ok, fail); }
}
function fallbackCopy(text, ok, fail){
  const ta=document.createElement('textarea'); ta.value=text; ta.style.position='fixed'; ta.style.left='-9999px'; document.body.appendChild(ta); ta.focus(); ta.select();
  try{ document.execCommand('copy'); ok(); } catch(e){ fail(e); }
  document.body.removeChild(ta);
}
function copyField(id, sourceEl=null, message='Copied.'){ copyText($(id).value || '', message || 'Copied.', sourceEl); }
function copyButton(text, label, message){ return `<button class="mini secondary copy-btn" data-copy="${esc(text)}" data-copy-message="${esc(message||'Copied.')}" title="${esc(message||'Copy')}">${esc(label)}</button>`; }
function metadataBlock(item){
  const text = item.text || '';
  const refText = item.reference_transcript || '';
  const refAudio = item.reference_audio || '';
  if(!text && !refText && !refAudio) return '';
  const meta = {engine:item.engine||'', role:item.role||'', voice_profile:item.profile||'', reference_audio:refAudio, reference_transcript:refText, synthesized_text:text, output_audio:item.output_path||item.path||item.output||'', created_at:item.created_at||''};
  return `<details class="meta-panel pref-metadata"><summary>view text / metadata</summary>
    <div class="row3">
      ${copyButton(text, 'copy synth text', 'Synthesized text copied.')}
      ${copyButton(refText, 'copy reference text', 'Reference text copied.')}
      ${copyButton(refAudio, 'copy reference path', 'Reference path copied.')}
    </div>
    <pre>${esc(JSON.stringify(meta, null, 2))}</pre>
  </details>`;
}
function setPrefVisible(cls, show){ document.querySelectorAll('.'+cls).forEach(el => el.classList.toggle('pref-hidden', !show)); }
function normalizeUiMode(mode){
  if(mode === 'beginner') return 'science_fair';
  if(['advanced','producer','science_fair','minimal','custom'].includes(mode)) return mode;
  return 'producer';
}
function modeLabel(mode){
  return ({advanced:'Show everything', producer:'Producer default', science_fair:'Hide the science fair', minimal:'Minimal', custom:'Custom'})[normalizeUiMode(mode)] || 'Producer default';
}
function presetChecks(mode){
  mode = normalizeUiMode(mode);
  if(mode === 'minimal') return {optAdvanced:false,optProfileTools:false,optExperimental:false,optMetadata:false,optLogs:false,optDelete:false};
  if(mode === 'science_fair') return {optAdvanced:false,optProfileTools:true,optExperimental:false,optMetadata:false,optLogs:false,optDelete:true};
  if(mode === 'advanced') return {optAdvanced:true,optProfileTools:true,optExperimental:true,optMetadata:true,optLogs:true,optDelete:true};
  if(mode === 'producer') return {optAdvanced:true,optProfileTools:true,optExperimental:false,optMetadata:true,optLogs:true,optDelete:true};
  return null;
}
function currentOptionChecks(){
  return {
    optAdvanced:$('optAdvanced')?.checked === true,
    optProfileTools:$('optProfileTools')?.checked === true,
    optExperimental:$('optExperimental')?.checked === true,
    optMetadata:$('optMetadata')?.checked === true,
    optLogs:$('optLogs')?.checked === true,
    optDelete:$('optDelete')?.checked === true,
  };
}
function checksEqual(a,b){ return Object.keys(a).every(k => !!a[k] === !!b[k]); }
function matchingPreset(){
  const cur=currentOptionChecks();
  for(const mode of ['advanced','producer','science_fair','minimal']){
    if(checksEqual(cur, presetChecks(mode))) return mode;
  }
  return 'custom';
}
function syncPrefsToPreset(){
  const sel=$('uiMode'); if(sel) sel.value = matchingPreset();
}
function applyUiPrefs(){
  const adv=$('optAdvanced')?.checked !== false;
  const prof=$('optProfileTools')?.checked !== false;
  const exp=$('optExperimental')?.checked === true;
  const meta=$('optMetadata')?.checked !== false;
  const logs=$('optLogs')?.checked !== false;
  const del=$('optDelete')?.checked !== false;
  const stickyTabs=$('optStickyTabs')?.checked === true;
  document.querySelectorAll('.tabs').forEach(el=>el.classList.toggle('sticky-tabs', stickyTabs));
  setPrefVisible('pref-advanced', adv);
  setPrefVisible('pref-profile-tools', prof);
  setPrefVisible('pref-experimental', exp);
  setPrefVisible('pref-metadata', meta);
  setPrefVisible('pref-logs', logs);
  setPrefVisible('pref-delete', del);
  if($('uiMode') && !$('uiMode').value) $('uiMode').value = matchingPreset();
  if(!logs && activeLogId) closeJobLog();
  applyLayoutPrefs();
}
function setOptionChecks(opts){
  for(const [id,val] of Object.entries(opts)){ const el=$(id); if(el) el.checked=!!val; }
  applyUiPrefs();
}
function clampNumber(value, min, max, fallback){
  const n = Number(value);
  if(!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.round(n)));
}
function moveJobsPanelContent(asTab){
  const content=$('jobsPanelContent');
  const tabMount=$('jobsTabMount');
  const sideMount=$('jobsPanelMount');
  if(!content || !tabMount || !sideMount) return;
  const target = asTab ? tabMount : sideMount;
  if(content.parentElement !== target) target.appendChild(content);
}
function applyLayoutPrefs(){
  const orientation = readFieldValue('optPanelOrientation', 'side') === 'stack' ? 'stack' : 'side';
  const jobsAsTab = readFieldChecked('optJobsAsTab', false);
  const opsWidth = clampNumber(readFieldValue('optOpsWidth', 560), 320, 900, 560);
  document.documentElement.style.setProperty('--ops-width', opsWidth + 'px');
  const label=$('opsWidthLabel'); if(label) label.textContent = opsWidth + 'px';
  document.body.classList.toggle('layout-stack', orientation === 'stack');
  document.body.classList.toggle('jobs-as-tab', jobsAsTab);
  const jobsTab=$('tab-jobs'); if(jobsTab) jobsTab.classList.toggle('hidden', !jobsAsTab);
  moveJobsPanelContent(jobsAsTab);
  if(!jobsAsTab && currentTabName === 'jobs') showTab('single');
  const status=$('layoutStatus');
  if(status){
    const orientText = orientation === 'stack' ? 'Top/bottom layout is active.' : 'Left/right layout is active.';
    const jobsText = jobsAsTab ? ' Jobs are hidden from the side panel and available as a tab.' : ' Jobs remain visible in their own panel.';
    status.innerHTML = '<span class="ok">'+esc(orientText + jobsText)+'</span>';
  }
}
function applyModePreset(mode='producer'){
  mode = normalizeUiMode(mode || 'producer');
  if($('uiMode')) $('uiMode').value = mode;
  const opts = presetChecks(mode);
  if(opts) setOptionChecks(opts);
  else applyUiPrefs();
  scheduleFormStateSave();
}
function readFieldValue(id, fallback=''){ const el=$(id); return el ? el.value : fallback; }
function readFieldChecked(id, fallback=false){ const el=$(id); return el ? !!el.checked : fallback; }
function setFieldValue(id, value){ const el=$(id); if(el && value !== undefined) el.value = value; }
function setFieldChecked(id, value){ const el=$(id); if(el && value !== undefined) el.checked = !!value; }
function globalNamingBody(){
  return {
    name:readFieldValue('globalName', ''),
    name_mode:readFieldValue('globalNameMode', 'none'),
    function_mode:readFieldValue('globalFunctionMode', 'none'),
    date_mode:readFieldValue('globalDateMode', 'none'),
    version_mode:readFieldValue('globalVersionMode', 'collision'),
    filename_template:readFieldValue('globalFilenameTemplate', '[source][version][.ext]')
  };
}
function buildTemplateFromControls(){
  const n = globalNamingBody();
  let base = '[source]';
  if(n.name_mode === 'prefix') base = '[custom]-' + base;
  else if(n.name_mode === 'suffix') base = base + '-[custom]';
  else if(n.name_mode === 'replace') base = '[custom]';
  if(n.function_mode === 'prefix') base = '[function]-' + base;
  else if(n.function_mode === 'suffix') base = base + '-[function]';
  if(n.date_mode === 'prefix') base = '[YYYYMMDD]-' + base;
  else if(n.date_mode === 'suffix') base = base + '-[YYYYMMDD]';
  return base + '[version][.ext]';
}
function buildFilenameTemplateFromControls(){
  setFieldValue('globalFilenameTemplate', buildTemplateFromControls());
  updateNamingSummaries();
  scheduleFormStateSave();
  logUiEvent('filename template updated from menus', {template:readFieldValue('globalFilenameTemplate','')});
}
function filenamePreviewTokens(functionLabel='extracted'){
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  const yyyy = String(d.getFullYear());
  const mm = pad(d.getMonth()+1);
  const dd = pad(d.getDate());
  let h = d.getHours();
  const m = pad(d.getMinutes());
  const ap = h >= 12 ? 'PM' : 'AM';
  const h12 = h % 12 || 12;
  return {
    source:'sample-source',
    custom:(readFieldValue('globalName','') || 'custom'),
    function:functionLabel,
    version:readFieldValue('globalVersionMode','collision') === 'always' ? '-v1' : '',
    ext:'mp3',
    '.ext':'.mp3',
    YYYYMMDD:yyyy+mm+dd,
    'YYYY-MM-DD':yyyy+'-'+mm+'-'+dd,
    year:yyyy,
    month:mm,
    day:dd,
    weekday:d.toLocaleDateString(undefined, {weekday:'long'}),
    time24:pad(h)+m,
    time24hour:pad(h)+m,
    time12:String(h12)+m+ap,
    'time-am-pm':String(h12)+m+ap,
    timestamp:yyyy+mm+dd+'_'+pad(h)+m+pad(d.getSeconds())
  };
}
function renderFilenamePreview(template, tokens){
  let out = template || '[source][version][.ext]';
  const keys = Object.keys(tokens).sort((a,b)=>b.length-a.length);
  for(const k of keys) out = out.split('['+k+']').join(tokens[k]);
  const unknown = Array.from(out.matchAll(/\[[^\]]+\]/g)).map(m=>m[0]);
  out = out.replace(/-{2,}/g,'-').replace(/_{2,}/g,'_').replace(/\s+/g,' ').replace(/^[ ._-]+|[ ._-]+$/g,'');
  if(!out.toLowerCase().endsWith('.mp3')) out += '.mp3';
  return {name:out, unknown:[...new Set(unknown)]};
}
function globalNamingSummaryText(){
  const n = globalNamingBody();
  const modeMap = {suffix:'custom suffix', prefix:'custom prefix', replace:'custom full base', none:'custom ignored'};
  const functionMap = {none:'no function naming', prefix:'function prefix', suffix:'function suffix'};
  const dateMap = {none:'no date', prefix:'date prefix', suffix:'date suffix'};
  const verMap = {collision:'version only on collision', always:'always versioned', none:'timestamp only on conflict'};
  const preview = renderFilenamePreview(n.filename_template, filenamePreviewTokens('extracted'));
  const warn = preview.unknown.length ? ' <span class="bad">Unknown token(s): '+esc(preview.unknown.join(', '))+'</span>' : '';
  return `Template: <code>${esc(n.filename_template || '[source][version][.ext]')}</code><br>Preview: <code>${esc(preview.name)}</code>${warn}<br><span class="small">${esc(modeMap[n.name_mode] || n.name_mode)}; ${esc(functionMap[n.function_mode] || n.function_mode)}; ${esc(dateMap[n.date_mode] || n.date_mode)}; ${esc(verMap[n.version_mode] || n.version_mode)}</span>`;
}
function updateNamingSummaries(){
  const txt = globalNamingSummaryText();
  const status=$('globalNamingStatus'); if(status) status.innerHTML = txt;
  const plain = (new DOMParser().parseFromString(txt, 'text/html').body.textContent || '').replace(/\s+/g,' ').trim();
  for(const id of ['audioNamingSummary','videoNamingSummary']){
    const el=$(id); if(el) el.textContent = plain;
  }
}
function insertFilenameToken(token){
  if(!token) return;
  const el=$('globalFilenameTemplate');
  if(!el) return;
  const start = el.selectionStart ?? el.value.length;
  const end = el.selectionEnd ?? el.value.length;
  el.value = el.value.slice(0,start) + token + el.value.slice(end);
  const pos = start + token.length;
  el.focus();
  try{ el.setSelectionRange(pos, pos); }catch(e){}
  updateNamingSummaries();
  scheduleFormStateSave();
}
function resetGlobalNamingDefaults(){
  setFieldValue('globalName', '');
  setFieldValue('globalNameMode', 'none');
  setFieldValue('globalFunctionMode', 'none');
  setFieldValue('globalDateMode', 'none');
  setFieldValue('globalVersionMode', 'collision');
  setFieldValue('globalFilenameTemplate', '[source][version][.ext]');
  updateNamingSummaries();
  scheduleFormStateSave();
  logUiEvent('reset global naming defaults');
}
const NOTICE_CATALOG = {
  audio_short_reference: {
    title:'Audio Lab short-reference advisory',
    appears:'Audio Lab',
    why:'CosyVoice has a hard reference-token extraction limit above roughly 30 seconds; Qwen/Cosy usually behave best with short matched reference clips; F5 remains experimental locally.',
    fix:'Set Audio Lab to create a 12-second engine-safe reference clip, then process the selected source.'
  },
  whisper_ready: {
    title:'Faster-Whisper ready notice',
    appears:'STT / Transcribe',
    why:'This confirms the local Faster-Whisper helper is available.',
    fix:'No repair needed. Restore only if we need to troubleshoot STT setup visibility.'
  },
  hf_token_setup: {
    title:'Hugging Face token/auth warning',
    appears:'STT / Transcribe',
    why:'An STT job saw a Hugging Face authentication/download warning, or the setup panel was opened manually from Maintenance.',
    fix:'Configure or test a local read-only token from Maintenance. Restore notice only for troubleshooting or setup visibility.'
  },
  profile_best_path: {
    title:'Profile best-path advisory',
    appears:'Profiles',
    why:'Original human reference clips with corrected transcripts produce more trustworthy reusable profiles than clone-of-clone generated audio.',
    fix:'No automatic repair is required. Use Create voice profile with original reference audio when available.'
  },
  video_permitted_use: {
    title:'Video Intake permitted-use reminder',
    appears:'Video Intake',
    why:'Video Intake can archive media from uploads or URLs, so the UI reminds the operator to use only owned, permitted, or otherwise allowed sources.',
    fix:'No automatic repair is available. Restore only if you want the reminder visible again.'
  },
  resemble_setup: {
    title:'Resemble Enhance setup/status apparatus',
    appears:'Resemble Enhance',
    why:'The installer and detector are helpful while setting up or repairing Resemble Enhance, but they take space once the isolated command is working.',
    fix:'Refresh Resemble status from Maintenance, restore the setup/status panel when needed, or open the Resemble tab and run the isolated test bench.'
  },
  whisper_gpu_setup: {
    title:'Whisper GPU support setup',
    appears:'STT / Transcribe',
    why:'GPU transcription needs local CUDA/cuDNN runtime libraries. Without them, STT may fall back to CPU.',
    fix:'Run the GPU dependency check, install/repair support, or test GPU transcription from Maintenance.'
  }
};
function noticeCatalogItem(id){ return NOTICE_CATALOG[id] || {title:id, appears:'Unknown', why:'No description available yet.', fix:'No automatic fix is available.'}; }
function applyNoticeVisibility(){
  document.querySelectorAll('[data-notice-id]').forEach(el=>{
    const id = el.dataset.noticeId || '';
    el.classList.toggle('hidden', dismissedNotices.has(id));
  });
}
function dismissNotice(id){
  if(!id) return;
  dismissedNotices.add(id);
  applyNoticeVisibility();
  renderMaintenance();
  scheduleFormStateSave();
  logUiEvent('notice dismissed', {id, title:noticeCatalogItem(id).title});
}
function restoreNotice(id){
  if(!id) return;
  dismissedNotices.delete(id);
  if(id === 'hf_token_setup') { localStorage.removeItem('ttsLabHfTokenSetupDismissed'); hfTokenSetupManuallyOpened = true; }
  if(id === 'whisper_gpu_setup') localStorage.removeItem('ttsLabGpuSetupHidden');
  if(id === 'whisper_ready') localStorage.removeItem('ttsLabWhisperReadyDismissed');
  applyNoticeVisibility();
  renderMaintenance();
  scheduleFormStateSave();
  if(id === 'hf_token_setup') updateHfTokenStatus(null);
  if(id === 'whisper_gpu_setup') showWhisperGpuSetup();
  if(id === 'whisper_ready') loadSttStatus();
  logUiEvent('notice restored', {id, title:noticeCatalogItem(id).title});
}
function renderMaintenance(){
  const list = $('dismissedNoticesList');
  if(list){
    const ids = Array.from(dismissedNotices);
    if(!ids.length){
      list.innerHTML = '<div class="maintenance-item">No notices are currently dismissed.</div>';
    } else {
      list.innerHTML = ids.map(id=>{
        const n = noticeCatalogItem(id);
        let fixBtn = '';
        if(id === 'audio_short_reference') fixBtn = '<button class="mini secondary" onclick="maintenancePrepareShortReference()">fix: set 12-second Audio Lab defaults</button>';
        if(id === 'hf_token_setup') fixBtn = '<button class="mini secondary" onclick="maintenanceOpenHfTokenSetup()">configure token</button><button class="mini secondary" onclick="maintenanceCheckHfToken()">check token status</button>';
        if(id === 'whisper_gpu_setup') fixBtn = '<button class="mini secondary" onclick="maintenanceOpenWhisperGpuSetup()">open GPU setup</button><button class="mini secondary" onclick="testWhisperGpuSupport()">test GPU support</button>';
        if(id === 'resemble_setup') fixBtn = '<button class="mini secondary" onclick="maintenanceCheckResemble()">check Resemble status</button><button class="mini secondary" onclick="repairResembleGitLfs()">install/repair Git LFS</button>';
        let openBtn = '';
        if(n.appears.includes('STT')) openBtn = `<button class="mini secondary" onclick="showTab('stt')">open STT</button>`;
        else if(n.appears.includes('Audio')) openBtn = `<button class="mini secondary" onclick="showTab('audio')">open Audio Lab</button>`;
        else if(n.appears.includes('Profiles')) openBtn = `<button class="mini secondary" onclick="showTab('profiles')">open Profiles</button>`;
        else if(n.appears.includes('Video')) openBtn = `<button class="mini secondary" onclick="showTab('video')">open Video Intake</button>`;
        else if(n.appears.includes('Resemble')) openBtn = `<button class="mini secondary" onclick="showTab('resemble')">open Resemble Enhance</button>`;
        return `<div class="maintenance-item"><b>${esc(n.title)}</b> <span class="pill">${esc(n.appears)}</span><div>${esc(n.why)}</div><div class="small"><b>Known fix:</b> ${esc(n.fix)}</div><div class="notice-actions">${fixBtn}${openBtn}<button class="mini secondary" onclick="restoreNotice('${esc(id)}')">restore notice</button></div></div>`;
      }).join('');
    }
  }
}

function yesNo(ok, good='ok', bad='missing'){
  return ok ? '<span class="ok">'+esc(good)+'</span>' : '<span class="bad">'+esc(bad)+'</span>';
}
function statusRow(label, ok, detail=''){
  return '<div><b>'+esc(label)+':</b> '+yesNo(!!ok)+(detail ? ' <span class="small">'+detail+'</span>' : '')+'</div>';
}
function renderStackStatus(d){
  lastStackStatus = d;
  const el = $('maintStackStatus');
  if(!el) return;
  const launcher = d.launcher || {};
  const installer = (d.stack_installer && d.stack_installer.best) || {};
  const engines = d.engines || {};
  const helpers = d.helpers || {};
  const video = d.video_downloader || {};
  const logs = d.logs || {};
  const engineRows = ['chatterbox','qwen3','cosyvoice','f5'].map(k=>{
    const e = engines[k] || {};
    const label = k === 'qwen3' ? 'Qwen3' : (k === 'cosyvoice' ? 'CosyVoice' : (k === 'f5' ? 'F5 experimental' : 'Chatterbox'));
    const ok = !!(e.exists && e.python_exists);
    const note = e.experimental ? ' <span class="warn">experimental</span>' : '';
    return statusRow(label, ok, '<code>'+esc(e.env_name || '')+'</code>'+note);
  }).join('');
  const helperRows = [
    ['Conda', helpers.conda && helpers.conda.available, '<code>'+esc((helpers.conda && helpers.conda.path) || '')+'</code>'],
    ['ffmpeg', helpers.ffmpeg && helpers.ffmpeg.available, '<code>'+esc((helpers.ffmpeg && helpers.ffmpeg.path) || '')+'</code>'],
    ['yt-dlp', helpers.yt_dlp && helpers.yt_dlp.available, '<code>'+esc((helpers.yt_dlp && helpers.yt_dlp.path) || 'optional fallback')+'</code>'],
    ['HandAI video-dl', video.ready, '<code>'+esc((video.commands || []).join(', ') || video.video_dl_dir || '')+'</code>'],
    ['Audacity', helpers.audacity && helpers.audacity.available, '<code>'+esc((helpers.audacity && helpers.audacity.command) || 'optional')+'</code>'],
    ['xdg-open', helpers.xdg_open && helpers.xdg_open.available, '<code>'+esc((helpers.xdg_open && helpers.xdg_open.path) || 'optional')+'</code>']
  ].map(r=>statusRow(r[0], r[1], r[2])).join('');
  const launcherDetail = launcher.error ? '<span class="bad">'+esc(launcher.error)+'</span>' : '<code>'+esc(launcher.path || '')+'</code>';
  const installerDetail = installer.exists ? '<code>'+esc(installer.path || '')+'</code>'+(installer.version ? ' v'+esc(installer.version) : '') : '<span class="warn">not found in common locations</span>';
  el.innerHTML = [
    '<div><b>Overall:</b> '+(d.ready ? '<span class="ok">green-path stack appears present.</span>' : '<span class="warn">stack needs attention or has optional/missing pieces.</span>')+'</div>',
    '<div><b>Web UI:</b> v'+esc(d.version || '')+' &nbsp; <b>Lab:</b> <code>'+esc(d.lab || '')+'</code></div>',
    statusRow('Launcher file', launcher.exists && launcher.executable, launcherDetail),
    statusRow('Launcher status command', launcher.status_ok, launcher.status_ran ? 'exit '+esc(launcher.returncode) : 'not run'),
    statusRow('Stack installer', installer.exists, installerDetail),
    '<details><summary>Engine environments</summary>'+engineRows+'</details>',
    '<details><summary>Helper tools</summary>'+helperRows+'</details>',
    '<details><summary>Log locations</summary><div><b>UI diagnostics:</b> <code>'+esc(logs.ui_diagnostics || '')+'</code></div><div><b>External actions:</b> <code>'+esc(logs.external_actions || '')+'</code></div><div><b>Stack installer:</b> <code>'+esc(logs.stack_installer || '')+'</code></div><div><b>Jobs:</b> <code>'+esc(logs.jobs || '')+'</code></div></details>'
  ].join('');
}
function maintenanceCheckStack(){
  const el=$('maintStackStatus'); if(el) el.textContent='Checking TTS Lab stack contract...';
  return api('/api/stack-status').then(d=>{ renderStackStatus(d); logUiEvent('maintenance stack status checked', {ready:!!d.ready}); return d; })
    .catch(err=>{ if(el) el.innerHTML='<span class="bad">Could not check stack status: '+esc(err)+'</span>'; });
}
function copyStackDiagnostics(btn){
  const text = lastStackStatus ? JSON.stringify(lastStackStatus, null, 2) : 'Stack status has not been checked yet.';
  copyText(text, 'Stack diagnostics copied.', btn);
}
function maintenancePrepareShortReference(){
  showTab('audio');
  setFieldValue('audioLabFormat', 'wav');
  setFieldValue('audioLabSampleRate', '24000');
  setFieldValue('audioLabChannels', '1');
  setFieldValue('audioLabTrimStart', '0');
  setFieldValue('audioLabTrimDuration', '12');
  setFieldValue('globalName', 'short-ref-12s');
  setFieldValue('globalNameMode', 'suffix');
  setFieldValue('globalVersionMode', 'always');
  setFieldChecked('audioLabNormalize', true);
  updateNamingSummaries();
  toggleAudioLabBitrate();
  const msg = 'Audio Lab prepared for a 12-second engine-safe reference derivative. Choose/confirm the source, then Process audio.';
  if($('audioLabStatus')) $('audioLabStatus').innerHTML = '<span class="ok">'+esc(msg)+'</span>';
  if($('maintAudioShortRefStatus')) $('maintAudioShortRefStatus').innerHTML = '<span class="ok">'+esc(msg)+'</span>';
  scheduleFormStateSave();
  focusPane('audio');
  logUiEvent('maintenance action: prepared Audio Lab short-reference defaults');
}
function maintenanceOpenHfTokenSetup(){
  showTab('stt');
  showHfTokenSetup();
  const box=$('hfTokenSetupBox'); if(box){ box.open=true; box.scrollIntoView({block:'start', behavior:'smooth'}); }
  logUiEvent('maintenance action: opened HF token setup');
}
function maintenanceCheckHfToken(){
  const el=$('maintHfTokenStatus'); if(el) el.textContent='Checking Hugging Face token status...';
  api('/api/hf-token/status').then(d=>{
    if(el) el.innerHTML = d.configured ? '<span class="ok">Configured:</span> <code>'+esc(d.masked || 'configured')+'</code>' : '<span class="warn">No saved token configured.</span> Use “Configure token” if model downloads are unreliable.';
    updateHfTokenStatus(d);
  }).catch(err=>{ if(el) el.innerHTML='<span class="bad">Could not check token: '+esc(err)+'</span>'; });
}
function maintenanceOpenWhisperGpuSetup(){
  showTab('stt');
  showWhisperGpuSetup();
  const box=$('whisperGpuSetupBox'); if(box){ box.open=true; box.scrollIntoView({block:'start', behavior:'smooth'}); }
  logUiEvent('maintenance action: opened Whisper GPU setup');
}
function maintenanceCheckWhisper(){
  const el=$('maintWhisperStatus'); if(el) el.textContent='Checking STT / Whisper status...';
  api('/api/stt/status').then(d=>{
    if(el) el.innerHTML = d.ready ? '<span class="ok">Faster-Whisper ready.</span> Python: <code>'+esc(d.python || '')+'</code>' : '<span class="bad">Faster-Whisper not ready:</span> '+esc(d.error || 'unknown error');
    loadSttStatus();
  }).catch(err=>{ if(el) el.innerHTML='<span class="bad">Could not check STT: '+esc(err)+'</span>'; });
}
function maintenanceOpenVideoIntake(){ showTab('video'); loadVideoIntakeStatus(); logUiEvent('maintenance action: opened Video Intake'); }
function maintenanceCheckVideoImporter(){
  const el=$('maintVideoStatus'); if(el) el.textContent='Checking Video URL importer...';
  api('/api/video-intake/status').then(d=>{
    const commands = (d.commands || []).join(', ') || 'none';
    if(el) el.innerHTML = d.ready ? '<span class="ok">URL importer ready.</span> Commands: <code>'+esc(commands)+'</code>' : '<span class="bad">URL importer not ready.</span> Directory: <code>'+esc(d.video_dl_dir || '')+'</code>; candidates: <code>'+esc((d.video_dl_candidates || []).join(', ') || 'none')+'</code>; yt-dlp: <code>'+esc(d.yt_dlp || 'not found')+'</code>';
    loadVideoIntakeStatus();
  }).catch(err=>{ if(el) el.innerHTML='<span class="bad">Could not check importer: '+esc(err)+'</span>'; });
}
function maintenanceCheckResemble(){
  const el=$('maintResembleStatus');
  if(el) el.textContent='Checking Resemble Enhance...';
  return api('/api/resemble/status').then(d=>{
    const gl = d.git_lfs || {};
    const glHtml = gl.available ? '<span class="ok">Git LFS available.</span>' : '<span class="bad">Git LFS missing.</span> Run Install/repair Git LFS before model-download tests.';
    if(el) el.innerHTML = (d.ready ? '<span class="ok">Ready.</span> <code>'+esc((d.best_command||[]).join(' '))+'</code>' : '<span class="warn">Resemble command not detected.</span>') + '<br>' + glHtml;
    renderResembleStatus(d);
    return d;
  }).catch(err=>{ if(el) el.innerHTML='<span class="bad">Check failed: '+esc(err)+'</span>'; });
}

function collectFormState(){
  return {
    remember_form:readFieldChecked('rememberForm', true),
    engine:readFieldValue('engine'),
    profile:readFieldValue('profileSelect'),
    role:readFieldValue('role'),
    ref:readFieldValue('ref'),
    ref_text:readFieldValue('refText'),
    text:readFieldValue('text'),
    x_vector_only:readFieldChecked('xVector', true),
    split_on_sentences:readFieldChecked('splitLong', true),
    ui_mode:readFieldValue('uiMode', 'producer'),
    show_advanced_options:readFieldChecked('optAdvanced', true),
    show_profile_tools:readFieldChecked('optProfileTools', true),
    show_experimental_profiles:readFieldChecked('optExperimental', false),
    show_metadata_buttons:readFieldChecked('optMetadata', true),
    show_job_logs:readFieldChecked('optLogs', true),
    show_delete_buttons:readFieldChecked('optDelete', true),
    sticky_tabs:readFieldChecked('optStickyTabs', false),
    panel_orientation:readFieldValue('optPanelOrientation', 'side'),
    jobs_as_tab:readFieldChecked('optJobsAsTab', false),
    operations_panel_width:clampNumber(readFieldValue('optOpsWidth', 560), 320, 900, 560),
    dismissed_notices:Array.from(dismissedNotices),
    global_name:readFieldValue('globalName', ''),
    global_name_mode:readFieldValue('globalNameMode', 'none'),
    global_function_mode:readFieldValue('globalFunctionMode', 'none'),
    global_date_mode:readFieldValue('globalDateMode', 'none'),
    global_version_mode:readFieldValue('globalVersionMode', 'collision'),
    global_filename_template:readFieldValue('globalFilenameTemplate', '[source][version][.ext]'),
    resemble_install_mode:readFieldValue('resembleInstallMode', 'auto'),
    resemble_device:readFieldValue('resembleDevice', 'auto'),
    video_format:readFieldValue('videoFormat', 'wav'),
    video_mp3_bitrate:readFieldValue('videoMp3Bitrate', '128k'),
    video_sample_rate:readFieldValue('videoSampleRate', 'unchanged'),
    video_channels:readFieldValue('videoChannels', 'unchanged'),
    video_normalize:readFieldChecked('videoNormalize', true),
    audio_lab_format:readFieldValue('audioLabFormat', 'unchanged'),
    audio_lab_mp3_bitrate:readFieldValue('audioLabMp3Bitrate', '192k'),
    audio_lab_sample_rate:readFieldValue('audioLabSampleRate', 'unchanged'),
    audio_lab_channels:readFieldValue('audioLabChannels', 'unchanged'),
    audio_lab_normalize:readFieldChecked('audioLabNormalize', true)
  };
}
function saveFormStateNow(){ if(!formStateLoaded) return Promise.resolve(); return api('/api/state', {method:'POST', body:JSON.stringify(collectFormState())}).catch(err=>console.warn('state save failed', err)); }
function scheduleFormStateSave(){ if(!formStateLoaded) return; clearTimeout(stateSaveTimer); stateSaveTimer=setTimeout(saveFormStateNow, 450); }
function restoreFormState(){
  return api('/api/state').then(data=>{
    const s=data.state || {};
    $('rememberForm').checked = s.remember_form !== false;
    if(s.engine && engines[s.engine]) $('engine').value=s.engine;
    if(s.profile !== undefined) $('profileSelect').value=s.profile || '';
    if(s.role !== undefined) $('role').value=s.role || 'EXEC';
    if(s.ref !== undefined) $('ref').value=s.ref || '';
    if(s.ref_text !== undefined) $('refText').value=s.ref_text || '';
    if(s.text !== undefined) $('text').value=s.text || '';
    if(s.x_vector_only !== undefined) $('xVector').checked=!!s.x_vector_only;
    if(s.split_on_sentences !== undefined) $('splitLong').checked=!!s.split_on_sentences;
    if(s.ui_mode !== undefined) $('uiMode').value=normalizeUiMode(s.ui_mode || 'producer');
    if(s.show_advanced_options !== undefined) $('optAdvanced').checked=!!s.show_advanced_options;
    if(s.show_profile_tools !== undefined) $('optProfileTools').checked=!!s.show_profile_tools;
    if(s.show_experimental_profiles !== undefined) $('optExperimental').checked=!!s.show_experimental_profiles;
    if(s.show_metadata_buttons !== undefined) $('optMetadata').checked=!!s.show_metadata_buttons;
    if(s.show_job_logs !== undefined) $('optLogs').checked=!!s.show_job_logs;
    if(s.show_delete_buttons !== undefined) $('optDelete').checked=!!s.show_delete_buttons;
    if(s.sticky_tabs !== undefined) $('optStickyTabs').checked=!!s.sticky_tabs;
    setFieldValue('optPanelOrientation', s.panel_orientation || 'side');
    setFieldChecked('optJobsAsTab', s.jobs_as_tab);
    setFieldValue('optOpsWidth', clampNumber(s.operations_panel_width, 320, 900, 560));
    setFieldValue('globalName', s.global_name);
    setFieldValue('globalNameMode', s.global_name_mode);
    setFieldValue('globalFunctionMode', s.global_function_mode);
    setFieldValue('globalDateMode', s.global_date_mode);
    setFieldValue('globalVersionMode', s.global_version_mode);
    setFieldValue('globalFilenameTemplate', s.global_filename_template);
    setFieldValue('resembleInstallMode', s.resemble_install_mode);
    setFieldValue('resembleDevice', s.resemble_device || 'auto');
    setFieldValue('videoFormat', s.video_format);
    setFieldValue('videoMp3Bitrate', s.video_mp3_bitrate);
    setFieldValue('videoSampleRate', s.video_sample_rate);
    setFieldValue('videoChannels', s.video_channels);
    setFieldChecked('videoNormalize', s.video_normalize);
    setFieldValue('audioLabFormat', s.audio_lab_format);
    setFieldValue('audioLabMp3Bitrate', s.audio_lab_mp3_bitrate);
    setFieldValue('audioLabSampleRate', s.audio_lab_sample_rate);
    setFieldValue('audioLabChannels', s.audio_lab_channels);
    setFieldChecked('audioLabNormalize', s.audio_lab_normalize);
    dismissedNotices = new Set(Array.isArray(s.dismissed_notices) ? s.dismissed_notices : []);
    if(localStorage.getItem('ttsLabHfTokenSetupDismissed') === '1') dismissedNotices.add('hf_token_setup');
    if(localStorage.getItem('ttsLabGpuSetupHidden') === '1') dismissedNotices.add('whisper_gpu_setup');
    if(localStorage.getItem('ttsLabWhisperReadyDismissed') === '1') dismissedNotices.add('whisper_ready');
    applyNoticeVisibility();
    renderMaintenance();
    toggleVideoBitrate();
    toggleAudioLabBitrate();
    updateNamingSummaries();
    updateEngineNote();
    applyUiPrefs();
    formStateLoaded = true;
    attachFormStateHandlers();
  });
}
function attachFormStateHandlers(){
  for(const id of ['engine','profileSelect','role','ref','refText','text','xVector','splitLong','rememberForm','uiMode','optAdvanced','optProfileTools','optExperimental','optMetadata','optLogs','optDelete','optStickyTabs','optPanelOrientation','optJobsAsTab','optOpsWidth','globalName','globalNameMode','globalFunctionMode','globalDateMode','globalVersionMode','globalFilenameTemplate','resembleInstallMode','resembleDevice','videoFormat','videoMp3Bitrate','videoSampleRate','videoChannels','videoNormalize','audioLabFormat','audioLabMp3Bitrate','audioLabSampleRate','audioLabChannels','audioLabNormalize']){
    const el=$(id); if(!el || el.dataset.stateHooked) continue;
    el.dataset.stateHooked='1'; el.addEventListener('input', ()=>{ updateNamingSummaries(); scheduleFormStateSave(); }); el.addEventListener('change', ()=>{ updateNamingSummaries(); scheduleFormStateSave(); });
  }
}
function clearRememberedForm(){
  if(!confirm('Clear the remembered Synthesize form? This will not delete any audio or profiles.')) return;
  api('/api/state/clear', {method:'POST', body:JSON.stringify({})}).then(()=>alert('Remembered form cleared. Current visible fields were not deleted.')).catch(alert);
}
function silenceCpuFallbackWarnings(){ localStorage.setItem('ttsLabSilenceCpuFallbackWarning','1'); lastJobsSig=''; refreshJobs(); }
function sttJobBlock(j){
  const txt = j.transcript || '';
  const path = j.source_path || '';
  const result = j.result || {};
  const meta = Object.keys(result).length ? JSON.stringify(result, null, 2) : '';
  const fallbackWarn = j.warning || result.fallback_warning || '';
  const showFallbackWarn = fallbackWarn && localStorage.getItem('ttsLabSilenceCpuFallbackWarning') !== '1';
  const warning = showFallbackWarn ? `<div class="warning-box bad"><b>GPU fallback warning:</b> Device=auto could not use CUDA, so this job used CPU instead.<br><span class="small">${esc(fallbackWarn.slice(0,500))}</span><br><button class="mini secondary" onclick="silenceCpuFallbackWarnings()">don’t warn me again for CPU fallback</button></div>` : (fallbackWarn ? `<div class="small warn">Using CPU fallback as configured.</div>` : '');
  const used = result.device ? `<div class="small">Requested: <code>${esc(result.requested_device || '')}</code> / Used: <code>${esc(result.device || '')}</code> / Compute: <code>${esc(result.compute_type || '')}</code></div>` : '';
  const preview = txt ? `<div class="small"><b>Transcript preview:</b> ${esc(txt.slice(0,260))}${txt.length>260?'...':''}</div>` : '';
  const buttons = txt ? `<div class="inline-tools pref-metadata">
      ${copyButton(txt, 'copy transcript', 'Transcript copied.')}
      <button class="mini secondary stt-load-btn" data-text="${esc(txt)}" data-path="${esc(path)}">load in STT tab</button>
      <button class="mini secondary stt-use-ref-btn" data-text="${esc(txt)}" data-path="${esc(path)}">use audio + transcript as reference</button>
      <button class="mini secondary stt-save-btn" data-jobid="${esc(j.id || '')}" data-text="${esc(txt)}" data-path="${esc(path)}">save beside source</button><span id="stt-save-status-${esc(j.id || '')}" class="small stt-save-status"></span>
    </div>` : '';
  const details = meta ? `<details class="pref-metadata"><summary>STT result metadata</summary>${copyButton(meta, 'copy metadata', 'STT metadata copied.')}<pre>${esc(meta)}</pre></details>` : '';
  return `${warning}${used}${preview}${buttons}${details}`;
}
function audioLabJobBlock(j){
  const result = j.result || {};
  const before = result.source_waveform_url || '';
  const after = result.output_waveform_url || '';
  const fmt = (result.output_format || (j.output_path||j.output||'').split('.').pop() || 'audio').toLowerCase();
  const waves = (before || after) ? `<div class="waveforms pref-metadata">
    ${before?`<div class="waveform-card"><div class="small"><b>Before</b></div><img src="${esc(before)}" alt="Before waveform"></div>`:''}
    ${after?`<div class="waveform-card"><div class="small"><b>After</b></div><img src="${esc(after)}" alt="After waveform"></div>`:''}
  </div>` : '';
  const rate = result.sample_rate ? ` · sample rate: <code>${esc(String(result.sample_rate))}</code>` : '';
  const chans = result.channels ? ` · channels: <code>${esc(String(result.channels))}</code>` : '';
  const br = result.mp3_bitrate ? ` · bitrate: <code>${esc(String(result.mp3_bitrate))}</code>` : '';
  const details = Object.keys(result).length ? `<div class="small">Output format: <code>${esc(fmt)}</code>${rate}${chans}${br}${result.normalize_dynaudnorm?' · normalized with dynaudnorm':''}</div>` : '';
  return `${details}${waves}`;
}
function cancelJob(id){
  if(!id) return;
  const status = $('cancel-status-'+id);
  if(status) status.innerHTML = '<span class="warn">Abort requested...</span>';
  api('/api/jobs/cancel', {method:'POST', body:JSON.stringify({job_id:id})})
    .then(r=>{
      if(status) status.innerHTML = r.ok ? '<span class="warn">'+esc(r.message || 'Abort requested.')+'</span>' : '<span class="bad">'+esc(r.message || 'Could not abort job.')+'</span>';
      lastJobsSig=''; refreshJobs(); startPoll();
    })
    .catch(err=>{ if(status) status.innerHTML='<span class="bad">Could not abort job: '+esc(err)+'</span>'; else console.warn('Could not abort job', err); });
}
function renderJobs(data){
  $('jobs').innerHTML = data.jobs.map(j=>{
    const title = `${j.kind}${j.engine?' / '+j.engine:''}${j.role?' / '+j.role:''}`;
    const isStt = j.kind === 'stt';
    return `<div class="job"><b>${esc(j.kind)} ${j.engine?'/ '+esc(j.engine):''}</b> <span class="${statusClass(j.status)}">${esc(j.status)}</span> ${j.kind==='historical-output'?'<span class="pill">recovered from output</span>':''}<br>
    <span class="small">${j.role?esc(j.role)+' — ':''}${esc((j.text||'').slice(0,150))}</span><br>
    ${isStt ? sttJobBlock(j) : ''}
    ${j.kind==='audio' ? audioLabJobBlock(j) : ''}
    ${j.kind==='video' ? videoJobBlock(j) : ''}
    ${j.kind==='resemble' ? resembleJobBlock(j) : ''}
    ${(!isStt && j.kind!=='video' && j.kind!=='resemble' && j.audio_url)?`<audio controls preload="none" src="${j.preview_url || j.audio_url}"></audio>${durationBadge(j.duration_seconds, false)}<br>${outputActions(j.output_path || j.output, j.text, j.id || '')} <a download href="${j.wav_url || j.audio_url}">download ${esc(((j.output_path||j.output||'').split('.').pop()||'audio').toLowerCase())}</a><br>${metadataBlock(j)}`:''}
    ${j.manifest_url?`<a download href="${j.manifest_url}">manifest</a><br>`:''}
    ${j.children&&j.children.length?`<details><summary>${j.children.length} batch lines</summary>${j.children.map(c=>`${c.ok?'✅':'❌'} ${esc(c.index)} ${esc(c.role)} ${c.audio_url?`<audio controls preload="none" src="${c.preview_url || c.audio_url}"></audio>${durationBadge(c.duration_seconds, false)} ${outputActions(c.output, c.text)} <a download href="${c.wav_url || c.audio_url}">download wav</a>`:''}<br>`).join('')}</details>`:''}
    ${j.error?`<div class="bad">${esc(j.error)}</div>`:''}
    ${(j.status==='queued'||j.status==='running'||j.status==='canceling')?`<button class="mini danger cancel-job-btn" data-jobid="${esc(j.id)}">abort job</button> <span id="cancel-status-${esc(j.id)}" class="small inline-status"></span>`:''}
    ${j.status==='canceled'?`<div class="small warn">${esc(j.warning || 'Canceled by user.')}</div>`:''}
    <button class="mini secondary view-log-btn pref-logs" data-jobid="${esc(j.id)}" data-title="${esc(title)}">view log</button></div>`;
  }).join('') || '<p class="small">No jobs yet.</p>';
  applyUiPrefs();
}
function detectHfAuthNoticeFromJobs(data){
  const hit = (data.jobs || []).find(j => j && j.kind === 'stt' && j.status === 'error' && /Hugging Face|HF_TOKEN|HF Hub|authentication/i.test(String(j.error || '') + ' ' + String(j.warning || '')));
  if(hit && !dismissedNotices.has('hf_token_setup')){
    if(!hfAuthIssueDetected) logUiEvent('HF token notice activated from STT job error', {job_id:hit.id, error:hit.error}, 'warn');
    hfAuthIssueDetected = true;
    updateHfTokenStatus(null);
    renderMaintenance();
  }
}
function refreshJobs(){
  return api('/api/jobs').then(data=>{
    detectHfAuthNoticeFromJobs(data);
    updateCurrentSttFromJobs(data);
    const active = data.jobs.some(j => j.status === 'queued' || j.status === 'running' || j.status === 'canceling');
    const sig = JSON.stringify(data.jobs.map(j => [j.id, j.status, j.returncode, j.error, j.warning, j.output, (j.children||[]).length, j.transcript||""]));
    // Avoid destroying/recreating <audio> elements while the user is listening.
    // Re-render only when something actually changed, and defer non-critical
    // visual refreshes if audio is playing.
    if(sig !== lastJobsSig && !anyAudioPlaying()){
      renderJobs(data);
      lastJobsSig = sig;
    } else if(sig !== lastJobsSig && active) {
      // Running status changed but user is listening. Keep audio stable; the
      // next manual/idle refresh will catch up.
      lastJobsSig = sig;
    }
    if(activeLogId) refreshActiveLog(false);
    return active;
  }).catch(err=>{ console.warn(err); return false; });
}
function loadProfiles(){ return api('/api/profiles').then(data=>{ profiles=data.profiles; renderProfileSelect(); renderProfiles(); updateRoleMapTemplate(); }); }
function updateRoleMapTemplate(){
  const first = profiles[0]?.slug || '';
  const second = profiles[1]?.slug || first;
  const third = profiles[2]?.slug || second;
  $('roleMap').value = JSON.stringify({
    "EXEC": {"engine":"chatterbox", "profile": first},
    "TUCKER": {"engine":"qwen3", "profile": second, "x_vector_only": true},
    "ANALYST": {"engine":"qwen3", "profile": third, "x_vector_only": true}
  }, null, 2);
}
function renderProfiles(){
  $('profilesList').innerHTML = '<h2>Voice profiles</h2>' + (profiles.map(p=>`<div class="card"><b>${esc(p.name)}</b> <span class="pill">${esc(p.slug)}</span> ${durationBadge(p.duration_seconds, p.duration_warning)} ${p.ok?'':'<span class="bad">missing audio</span>'}<br>
    <span class="small">${esc(p.speaker||'')} ${p.style?'- '+esc(p.style):''}${p.duration_warning?' — under 10 seconds; consider replacing for Chatterbox/ElevenLabs-style references.':''}</span>
    <audio controls preload="none" src="${p.audio_url}"></audio>
    <button class="mini secondary" onclick="useProfile('${esc(p.slug)}')">use for synthesis</button>
    <a class="pill pref-profile-tools" download href="${p.export_url}">Download profile ZIP</a>
    <button class="mini danger pref-delete" onclick="requestDeleteProfile('${esc(p.slug)}', '${esc(p.name)}')">delete profile</button>
    <div id="delete-profile-${esc(p.slug)}" class="small"></div>
    <details class="pref-metadata"><summary>transcript / notes</summary>${copyButton(p.transcript||'', 'copy transcript', 'Profile transcript copied.')} ${copyButton(p.audio_path||'', 'copy path', 'Profile audio path copied.')}<pre>${esc(p.transcript||'(no transcript)')}</pre><div class="small">${esc(p.notes||'')}</div><code>${esc(p.audio_path)}</code></details>
    </div>`).join('') || '<p class="small">No voice profiles yet.</p>');
  applyUiPrefs();
}
function useProfile(slug){ showTab('single'); $('profileSelect').value=slug; applySelectedProfile(); }

function requestDeleteProfile(slug, name){
  const box = $('delete-profile-' + slug);
  if(!box) return;
  box.innerHTML = `<div class="warning-box"><b>Delete voice profile “${esc(name)}”?</b><br>This removes the profile folder, saved audio, transcript, and metadata.<div class="inline-tools"><button class="mini secondary" onclick="cancelDeleteProfile('${esc(slug)}')">Cancel</button><button class="mini danger" onclick="deleteProfile('${esc(slug)}')">Delete ${esc(name)}</button></div></div>`;
}
function cancelDeleteProfile(slug){ const box=$('delete-profile-' + slug); if(box) box.innerHTML=''; }
function deleteProfile(slug){
  const box=$('delete-profile-' + slug);
  if(box) box.innerHTML='Deleting profile...';
  api('/api/delete-profile', {method:'POST', body:JSON.stringify({slug})})
    .then(r=>{ loadProfiles(); $('synthProfileStatus').innerHTML='<span class="ok">Deleted profile:</span> '+esc(r.name || slug); })
    .catch(err=>{ if(box) box.innerHTML='<span class="bad">Delete failed: '+esc(err)+'</span>'; });
}
function installWhisperCudaSupport(){
  $('sttMaintenanceStatus').innerHTML = 'Queued Whisper GPU support repair. Watch Jobs for logs.'; if($('maintWhisperStatus')) $('maintWhisperStatus').innerHTML='<span class="ok">Queued Whisper GPU support repair.</span> Watch Jobs for logs.';
  api('/api/setup/whisper-cuda', {method:'POST', body:JSON.stringify({})}).then(()=>{ lastJobsSig=''; refreshJobs(); startPoll(); }).catch(err=>{ $('sttMaintenanceStatus').innerHTML='<span class="bad">Could not queue repair: '+esc(err)+'</span>'; if($('maintWhisperStatus')) $('maintWhisperStatus').innerHTML='<span class="bad">Could not queue repair: '+esc(err)+'</span>'; });
}
function testWhisperGpuSupport(){
  const src = sttSources.find(x=>x.path === $('sttSource').value) || {};
  const path = $('sttSource').value || src.path || '';
  const model = $('sttModel') ? $('sttModel').value : 'tiny';
  const language = $('sttLanguage') ? $('sttLanguage').value : 'auto';
  $('sttMaintenanceStatus').innerHTML = 'Queued real Whisper GPU transcription test. Watch Jobs for logs.'; if($('maintWhisperStatus')) $('maintWhisperStatus').innerHTML='<span class="ok">Queued real Whisper GPU transcription test.</span> Watch Jobs for logs.';
  api('/api/stt/test-gpu', {method:'POST', body:JSON.stringify({path, model, language})})
    .then(()=>{ lastJobsSig=''; refreshJobs(); startPoll(); })
    .catch(err=>{ $('sttMaintenanceStatus').innerHTML='<span class="bad">Could not queue GPU test: '+esc(err)+'</span>'; if($('maintWhisperStatus')) $('maintWhisperStatus').innerHTML='<span class="bad">Could not queue GPU test: '+esc(err)+'</span>'; });
}
function restartWebUi(){
  $('sttMaintenanceStatus').innerHTML = 'Restarting Web UI... browser will reconnect shortly.';
  api('/api/restart', {method:'POST', body:JSON.stringify({})}).catch(()=>{});
  setTimeout(()=>{ location.reload(); }, 1800);
}
async function createProfileFromForm(){
  const audio = $('profileAudioUpload').files[0]; if(!audio){ if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="bad">Choose reference audio first, or use the pending source panel above.</span>'; return; }
  let transcript = $('profileTranscript').value;
  const tfile = $('profileTranscriptUpload').files[0]; if(tfile && !transcript.trim()) transcript = await fileToText(tfile);
  const body = {name:$('profileName').value || audio.name.replace(/\.[^.]+$/,''), speaker:$('profileSpeaker').value, style:$('profileStyle').value, notes:$('profileNotes').value, audio_filename:audio.name, audio_base64:await fileToB64(audio), transcript_text:transcript};
  api('/api/create-profile', {method:'POST', body:JSON.stringify(body)}).then(r=>{ if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="ok">Created voice profile:</span> <b>'+esc(r.profile.name)+'</b>'; loadProfiles(); useProfile(r.profile.slug); }).catch(err=>{ if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="bad">Could not create profile: '+esc(err)+'</span>'; });
}
async function importProfileZip(){ const f=$('profileZipUpload').files[0]; if(!f){ if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="bad">Choose a ZIP first.</span>'; return; } api('/api/import-profile-zip', {method:'POST', body:JSON.stringify({filename:f.name, zip_base64:await fileToB64(f)})}).then(r=>{ if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="ok">Imported profile ZIP:</span> <b>'+esc(r.profile.name)+'</b>'; loadProfiles(); useProfile(r.profile.slug); }).catch(err=>{ if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="bad">Could not import ZIP: '+esc(err)+'</span>'; }); }
function loadRefs(){
  return api('/api/refs').then(data=>{
    const html = data.refs.map(r=>`<div class="card"><b>${esc(r.name)}</b> <span class="pill">${Math.round(r.size/1024)} KB</span> ${durationBadge(r.duration_seconds, r.duration_warning)}<audio controls preload="none" src="${r.audio_url}"></audio>${actionButton('use as temporary reference', 'set-reference', {path:r.path, transcript:r.transcript||''})}${actionButton('save as profile', 'create-profile', {path:r.path, transcript:r.transcript||''}, 'secondary pref-profile-tools')}<br><code>${esc(r.path)}</code>${r.transcript?`<details class="pref-metadata"><summary>transcript</summary>${copyButton(r.transcript||'', 'copy transcript', 'Reference transcript copied.')}<pre>${esc(r.transcript)}</pre></details>`:''}</div>`).join('') || 'No reference files found.';
    $('refsList').innerHTML = '<h3>Loose references</h3>' + html;
    applyUiPrefs();
  });
}
function setReference(path, transcript){
  if(!path){ logUiEvent('set-reference refused: missing path', null, 'warn'); return; }
  logUiEvent('handoff start: use as Synthesize reference', {path, transcript_chars:String(transcript||'').length});
  showTab('single');
  const profileSelect=$('profileSelect'), ref=$('ref'), refText=$('refText');
  if(!profileSelect || !ref || !refText){ logUiEvent('Synthesize handoff failed: required field missing', {profileSelect:!!profileSelect, ref:!!ref, refText:!!refText}, 'error'); return; }
  profileSelect.value='';
  ref.value=path;
  refText.value=transcript||'';
  if($('synthRefUploadStatus')) $('synthRefUploadStatus').innerHTML='<span class="ok">Loaded temporary Synthesize reference.</span><br><span class="small"><code>'+esc(path)+'</code></span>';
  focusPane('single');
  scheduleFormStateSave();
  logUiEvent('handoff success: Synthesize reference loaded', {path});
}
function saveCurrentReferenceProfile(){
  const path = $('ref').value.trim();
  const transcript = $('refText').value || '';
  const name = ($('role').value || '').trim();
  if(!path){ $('synthProfileStatus').innerHTML='<span class="bad">Choose or upload reference audio first.</span>'; return; }
  if(!name){ $('synthProfileStatus').innerHTML='<span class="bad">Enter a Role/name first. That name is used for the saved voice profile.</span>'; return; }
  $('synthProfileStatus').innerHTML = 'Saving voice profile <b>'+esc(name)+'</b>...';
  api('/api/create-profile', {method:'POST', body:JSON.stringify({name, source_audio_path:path, transcript_text:transcript, source:'manual-reference-fields'})})
    .then(r=>{ $('synthProfileStatus').innerHTML='<span class="ok">Saved voice profile:</span> <b>'+esc(r.profile.name)+'</b>'; loadProfiles().then(()=>useProfile(r.profile.slug)); })
    .catch(err=>{ $('synthProfileStatus').innerHTML='<span class="bad">Could not save profile: '+esc(err)+'</span>'; });
}

function defaultProfileNameFromPath(path){
  return String(path || '').split('/').pop().replace(/\.[^.]+$/,'');
}
function startProfileDraftFromSource(path, transcript='', experimental=false){
  if(!path){ logUiEvent('profile draft refused: missing path', null, 'warn'); return; }
  pendingProfileSource = path;
  pendingProfileTranscript = transcript || '';
  pendingProfileExperimental = !!experimental;
  const name = defaultProfileNameFromPath(path);
  logUiEvent(experimental ? 'handoff start: draft experimental profile' : 'handoff start: draft voice profile', {path, transcript_chars:String(transcript||'').length});
  showTab('profiles');
  if($('profileName')) $('profileName').value = name;
  if($('profileTranscript')) $('profileTranscript').value = transcript || '';
  if($('profileAudioUpload')) $('profileAudioUpload').value = '';
  const box = $('pendingProfileBox');
  if(box){
    box.classList.remove('hidden');
    box.innerHTML = `${experimental ? '<b>Experimental generated-output profile draft.</b><br><span class="bad">Generated audio is a copy, not original human reference audio. Using it as a profile can compound artifacts over later generations.</span>' : '<b>Voice profile draft from existing audio.</b>'}<br>Source audio:<br><code>${esc(path)}</code><br><span class="small">Review/edit the profile name, speaker, style, transcript, and notes below. Then create the profile from this saved source.</span><div class="inline-tools"><button class="mini secondary" type="button" onclick="clearPendingProfileDraft()">Cancel draft</button><button class="mini" type="button" onclick="createPendingProfileDraft()">${experimental ? 'Create experimental profile' : 'Create profile from selected audio'}</button></div>`;
  }
  if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="ok">Profile draft loaded. Review the fields, then use the inline create button.</span>';
  focusPane('profiles');
}
function clearPendingProfileDraft(){
  pendingProfileSource = null;
  pendingProfileTranscript = '';
  pendingProfileExperimental = false;
  const box = $('pendingProfileBox');
  if(box){ box.classList.add('hidden'); box.innerHTML=''; }
  if($('profileActionStatus')) $('profileActionStatus').textContent='Profile draft canceled.';
  logUiEvent('profile draft canceled');
}
function createPendingProfileDraft(){
  const path = pendingProfileSource || '';
  if(!path){ if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="bad">No pending profile source is selected.</span>'; logUiEvent('create pending profile refused: no source', null, 'warn'); return; }
  const name = ($('profileName') ? $('profileName').value : '').trim() || defaultProfileNameFromPath(path);
  const transcript = $('profileTranscript') ? $('profileTranscript').value : (pendingProfileTranscript || '');
  const speaker = $('profileSpeaker') ? $('profileSpeaker').value : '';
  const style = $('profileStyle') ? $('profileStyle').value : '';
  const notes = $('profileNotes') ? $('profileNotes').value : '';
  if($('profileActionStatus')) $('profileActionStatus').innerHTML='Creating profile <b>'+esc(name)+'</b> from saved source...';
  const body = pendingProfileExperimental
    ? {path, name}
    : {name, speaker, style, notes, source_audio_path:path, transcript_text:transcript, source:'job-handoff-inline'};
  const endpoint = pendingProfileExperimental ? '/api/promote-output' : '/api/create-profile';
  logUiEvent(pendingProfileExperimental ? 'API start: create experimental profile' : 'API start: create voice profile', {endpoint, path, name});
  api(endpoint, {method:'POST', body:JSON.stringify(body)})
    .then(r=>{
      const created = r.profile || {};
      pendingProfileSource = null; pendingProfileTranscript = ''; pendingProfileExperimental = false;
      const box = $('pendingProfileBox'); if(box){ box.classList.add('hidden'); box.innerHTML=''; }
      return loadProfiles().then(()=>{
        showTab('profiles');
        focusPane('profiles');
        if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="ok">Created voice profile:</span> <b>'+esc(created.name || name)+'</b>';
        logUiEvent('handoff success: voice profile created', {name:created.name || name, slug:created.slug || '', path});
      });
    })
    .catch(err=>{ logUiEvent('handoff failed: create voice profile', {path, error:String(err)}, 'error'); if($('profileActionStatus')) $('profileActionStatus').innerHTML='<span class="bad">Could not create profile: '+esc(err)+'</span>'; });
}
function createProfileFromLoose(path, transcript){
  startProfileDraftFromSource(path, transcript || '', false);
}
async function uploadRef(){
  const file = $('refUpload').files[0]; if(!file){ alert('Pick an audio file first.'); return; }
  const body = {filename:$('refUploadName').value || file.name, data_base64:await fileToB64(file), transcript_text:$('refUploadTranscript').value};
  api('/api/upload-ref', {method:'POST', body:JSON.stringify(body)}).then(r=>{ setReference(r.path, r.transcript||''); loadRefs(); }).catch(alert);
}
function chooseSynthRefUpload(){ $('synthRefUpload').value=''; $('synthRefUpload').click(); }
async function uploadSynthRef(){
  const file = $('synthRefUpload').files[0]; if(!file) return;
  const keepTranscript = $('refText').value || '';
  $('synthRefUploadStatus').textContent = 'Uploading ' + file.name + '...';
  const body = {filename:file.name, data_base64:await fileToB64(file), transcript_text:''};
  api('/api/upload-ref', {method:'POST', body:JSON.stringify(body)})
    .then(r=>{ setReference(r.path, keepTranscript); loadRefs(); $('synthRefUploadStatus').innerHTML = `<span class="ok">Uploaded reference audio:</span> <b>${esc(r.name || file.name)}</b> ${r.duration_seconds?`<span class="pill">${esc(fmtDuration(r.duration_seconds))}</span>`:''}<br><span class="small">Saved to <code>${esc(r.path)}</code> and filled Reference audio path.</span>`; })
    .catch(err=>{ $('synthRefUploadStatus').innerHTML='<span class="bad">Upload failed: '+esc(err)+'</span>'; });
}
function loadOutputs(force=false, overridePlayback=false){
  return api('/api/outputs').then(data=>{
    const sig = JSON.stringify(data.outputs.map(o => [o.path, o.size, o.mtime, o.preview_url, o.wav_url, o.text]));
    if(!force && sig === lastOutputsSig) return;
    if(!overridePlayback && anyAudioPlaying()) return;
    $('outputs').innerHTML = data.outputs.map(o=>`<div class="output"><b>${esc(o.name)}</b> ${o.engine?`<span class="pill">${esc(o.engine)}</span>`:''} ${o.role?`<span class="pill">${esc(o.role)}</span>`:''} <span class="pill">${Math.round(o.size/1024)} KB</span> ${durationBadge(o.duration_seconds, false)}
    <audio controls preload="none" src="${o.preview_url || o.audio_url}"></audio>
    ${outputActions(o.path, o.text||'')}
    <a class="pill" download href="${o.download_url || o.wav_url || o.audio_url}">download ${esc(o.download_label || ((o.path||'').split('.').pop() || 'audio'))}</a>
    ${metadataBlock(o)}
  </div>`).join('') || 'No outputs found.';
    lastOutputsSig = sig;
    applyUiPrefs();
  }).catch(console.warn);
}
function promoteOutput(path){
  startProfileDraftFromSource(path, '', true);
}

function deleteOutput(path, name){
  if(!confirm('Delete this generated audio file from Recent audio?\n\n' + name + '\n\nThis also removes its metadata sidecar and hidden chunk parts when present.')) return;
  api('/api/delete-output', {method:'POST', body:JSON.stringify({path})})
    .then(()=>{ lastOutputsSig=''; loadOutputs(true, true); lastJobsSig=''; refreshJobs(); })
    .catch(alert);
}

let sttSources = [];
let currentSttSavedTranscript = "";
let currentSttSavedTranscriptLabel = "";
function loadSttStatus(){
  return api('/api/stt/status').then(d=>{
    const ok = d.ready;
    const dismissed = localStorage.getItem('ttsLabWhisperReadyDismissed') === '1';
    $('sttStatus').className = ok ? 'warning-box ok' : 'warning-box';
    $('sttStatus').classList.toggle('hidden', ok && dismissed);
    $('sttStatus').innerHTML = ok
      ? `<b>Faster-Whisper ready.</b> Python: <code>${esc(d.python)}</code><br><span class="small">Helper: <code>${esc(d.helper)}</code></span><br><button class="mini secondary" onclick="dismissWhisperReadyNotice()">dismiss this notice</button>`
      : `<b>Faster-Whisper not ready yet.</b><br><span class="small">Run this once in a terminal, then restart the web UI:<br><code>${esc(d.install_command || '/home/user/tts-lab/install-whisper.sh')}</code><br>${esc(d.error || '')}</span>`;
    updateHfTokenStatus(d.hf_token || null);
    if(localStorage.getItem('ttsLabGpuSetupHidden') === '1' && $('whisperGpuSetupBox')) $('whisperGpuSetupBox').classList.add('hidden');
  }).catch(err=>{ $('sttStatus').textContent = 'Could not check STT status: ' + err; });
}
function dismissWhisperReadyNotice(){ localStorage.setItem('ttsLabWhisperReadyDismissed', '1'); dismissedNotices.add('whisper_ready'); $('sttStatus').classList.add('hidden'); renderMaintenance(); scheduleFormStateSave(); logUiEvent('notice dismissed', {id:'whisper_ready'}); }
function hideWhisperGpuSetup(){ localStorage.setItem('ttsLabGpuSetupHidden','1'); dismissedNotices.add('whisper_gpu_setup'); const box=$('whisperGpuSetupBox'); if(box) box.classList.add('hidden'); if($('sttMaintenanceStatus')) $('sttMaintenanceStatus').innerHTML='Whisper GPU support configured or hidden. <button class="mini secondary" onclick="showWhisperGpuSetup()">show GPU setup</button>'; renderMaintenance(); scheduleFormStateSave(); logUiEvent('notice dismissed', {id:'whisper_gpu_setup'}); }
function showWhisperGpuSetup(){ localStorage.removeItem('ttsLabGpuSetupHidden'); dismissedNotices.delete('whisper_gpu_setup'); const box=$('whisperGpuSetupBox'); if(box) box.classList.remove('hidden'); renderMaintenance(); scheduleFormStateSave(); }
function updateHfTokenStatus(data){
  if(!$('hfTokenStatus')) return;
  if(!data){ api('/api/hf-token/status').then(updateHfTokenStatus).catch(err=>{$('hfTokenStatus').textContent='Could not check token status: '+err;}); return; }
  const dismissed = dismissedNotices.has('hf_token_setup') || localStorage.getItem('ttsLabHfTokenSetupDismissed') === '1';
  const configuredHtml = `<b>Saved token:</b> <code>${esc(data.masked || 'configured')}</code> <span class="ok">configured locally</span> <button class="mini secondary" onclick="dismissHfTokenSetup()">dismiss token setup</button>`;
  $('hfTokenStatus').innerHTML = data.configured ? configuredHtml : `<b>Saved token:</b> <span class="warn">none configured</span>`;
  const box=$('hfTokenSetupBox'), compact=$('hfTokenCompactStatus');
  if(compact) compact.innerHTML = '';
  const shouldShow = hfTokenSetupManuallyOpened || (hfAuthIssueDetected && !dismissed);
  if(box){
    box.classList.toggle('hidden', !shouldShow);
    if(shouldShow && !box.open) box.open = true;
  }
}
function dismissHfTokenSetup(){ localStorage.setItem('ttsLabHfTokenSetupDismissed','1'); dismissedNotices.add('hf_token_setup'); hfTokenSetupManuallyOpened=false; hfAuthIssueDetected=false; updateHfTokenStatus(null); renderMaintenance(); scheduleFormStateSave(); logUiEvent('notice dismissed', {id:'hf_token_setup'}); }
function showHfTokenSetup(){ localStorage.removeItem('ttsLabHfTokenSetupDismissed'); dismissedNotices.delete('hf_token_setup'); hfTokenSetupManuallyOpened=true; updateHfTokenStatus(null); renderMaintenance(); scheduleFormStateSave(); }
function saveHfToken(){
  const token = $('hfTokenInput').value.trim();
  if(!token){ $('hfTokenStatus').innerHTML='<span class="bad">Paste a read-only token first.</span>'; return; }
  api('/api/hf-token/save', {method:'POST', body:JSON.stringify({token})}).then(r=>{ $('hfTokenInput').value=''; localStorage.removeItem('ttsLabHfTokenSetupDismissed'); dismissedNotices.delete('hf_token_setup'); updateHfTokenStatus(r); $('sttMeta').textContent='Saved Hugging Face token locally. It will be used for future STT model downloads.'; }).catch(err=>{ $('hfTokenStatus').innerHTML='<span class="bad">Could not save token: '+esc(err)+'</span>'; });
}
function testHfToken(){
  $('hfTokenStatus').innerHTML='Testing saved Hugging Face token...';
  api('/api/hf-token/test', {method:'POST', body:JSON.stringify({})}).then(r=>{ $('hfTokenStatus').innerHTML = (r.ok?'<span class="ok">':'<span class="bad">') + esc(r.message || '') + '</span>' + (r.ok ? ' <button class="mini secondary" onclick="dismissHfTokenSetup()">dismiss token setup</button>' : ''); }).catch(err=>{ $('hfTokenStatus').innerHTML='<span class="bad">Token test failed: '+esc(err)+'</span>'; });
}
function forgetHfToken(){
  if(!confirm('Forget the saved Hugging Face token from this local machine?')) return;
  api('/api/hf-token/forget', {method:'POST', body:JSON.stringify({})}).then(r=>{ localStorage.removeItem('ttsLabHfTokenSetupDismissed'); dismissedNotices.delete('hf_token_setup'); updateHfTokenStatus(r); $('sttMeta').textContent='Forgot saved Hugging Face token.'; }).catch(err=>{ $('hfTokenStatus').innerHTML='<span class="bad">Could not forget token: '+esc(err)+'</span>'; });
}
function loadSttSources(preferredPath=''){
  const want = preferredPath || ($('sttSource') ? $('sttSource').value : '') || lastSttSelectedPath || '';
  return api('/api/stt/sources').then(data=>{
    sttSources = data.sources || [];
    const sel=$('sttSource'); sel.innerHTML='';
    for(const src of sttSources){ const o=document.createElement('option'); o.value=src.path; o.textContent=src.label; sel.appendChild(o); }
    if(want && Array.from(sel.options).some(o=>o.value===want)) sel.value=want;
    selectSttSource();
  }).catch(console.warn);
}
function loadSavedTranscriptForSelectedStt(){
  if(!currentSttSavedTranscript){ $('sttSavedTranscriptNotice').textContent='No saved transcript is available for the selected audio.'; return; }
  $('sttTranscript').value = currentSttSavedTranscript;
  $('sttMeta').textContent = 'Loaded ' + (currentSttSavedTranscriptLabel || 'saved transcript') + ' for the selected audio. This text is not used as a Whisper prompt unless a future explicit prompt feature is added.';
}
function selectSttSource(){
  const path=$('sttSource').value || '';
  $('sttSourcePath').textContent = path;
  const src = sttSources.find(s=>s.path===path);
  currentSttSavedTranscript = (src && src.transcript) ? src.transcript : '';
  currentSttSavedTranscriptLabel = (src && src.transcript_label) ? src.transcript_label : 'saved transcript';
  if(path !== lastSttSelectedPath){
    $('sttTranscript').value = '';
    $('sttMeta').textContent = 'Selected audio to transcribe. Transcript draft will stay blank until Whisper finishes, or until you explicitly load a saved transcript.';
    lastSttSelectedPath = path;
    currentSttJobId = null;
  }
  if(currentSttSavedTranscript){
    $('sttSavedTranscriptNotice').innerHTML = `<span class="warn">Saved transcript exists for this selected audio (${esc(currentSttSavedTranscriptLabel)}).</span> It is not sent to Whisper. <button class="mini secondary" onclick="loadSavedTranscriptForSelectedStt()">Load saved transcript into draft</button>`;
  } else {
    $('sttSavedTranscriptNotice').textContent = 'No saved transcript found for this selected audio.';
  }
}
async function uploadSttAudio(){
  const file=$('sttUpload').files[0]; if(!file){ $('sttUploadStatus').innerHTML='<span class="bad">Choose an audio file first.</span>'; return; }
  $('sttUploadStatus').textContent = 'Uploading ' + file.name + '...';
  const body={filename:$('sttUploadName').value || file.name, data_base64:await fileToB64(file)};
  api('/api/stt/upload', {method:'POST', body:JSON.stringify(body)}).then(r=>{
    $('sttTranscript').value='';
    $('sttUploadStatus').innerHTML = `<span class="ok">Uploaded:</span> <b>${esc(r.name || file.name)}</b> ${r.duration_seconds?`<span class="pill">${esc(fmtDuration(r.duration_seconds))}</span>`:''}<br><span class="small">Saved to <code>${esc(r.path)}</code> and selected as audio source.</span>`;
    loadSttSources(r.path).then(()=>{ $('sttSource').value=r.path; selectSttSource(); });
  }).catch(err=>{ $('sttUploadStatus').innerHTML='<span class="bad">Upload failed: '+esc(err)+'</span>'; });
}
function transcribeStt(){
  const path=$('sttSource').value || '';
  if(!path){ alert('Choose an audio source first.'); return; }
  $('sttTranscript').value = '';
  $('sttMeta').textContent = 'Queued transcription job. Watch the Jobs panel for status and logs. First run may download/load the model and take a while.';
  const body={path, model:$('sttModel').value, language:$('sttLanguage').value, device:$('sttDevice').value, compute_type:$('sttCompute') ? $('sttCompute').value : 'auto'};
  api('/api/stt/transcribe', {method:'POST', body:JSON.stringify(body)}).then(r=>{
    currentSttJobId = r.job && r.job.id;
    lastJobsSig='';
    refreshJobs();
    startPoll();
  }).catch(err=>{ $('sttMeta').textContent = 'Could not queue transcription: ' + err; });
}
function updateCurrentSttFromJobs(data){
  if(!currentSttJobId) return;
  const j=(data.jobs||[]).find(x=>x.id===currentSttJobId);
  if(!j) return;
  if(j.status === 'done'){
    $('sttTranscript').value = j.transcript || '';
    $('sttMeta').textContent = JSON.stringify(j.result || j, null, 2);
    currentSttJobId = null;
  } else if(j.status === 'error' || j.status === 'canceled'){
    $('sttMeta').textContent = j.status === 'canceled' ? 'Transcription canceled. Open the STT job log in Jobs for details.' : 'Transcription failed. Open the STT job log in Jobs for details.\n\n' + (j.error || 'Unknown error');
    currentSttJobId = null;
  } else {
    $('sttMeta').textContent = `Transcription ${j.status}... open the STT job log in Jobs for details.`;
  }
}
function useSttJobTranscript(text, path){
  showTab('stt');
  if(path){
    const sel=$('sttSource');
    const exists=Array.from(sel.options).some(o=>o.value===path);
    if(exists){ sel.value=path; $('sttSourcePath').textContent=path; lastSttSelectedPath=path; }
  }
  $('sttTranscript').value = text || '';
  $('sttMeta').textContent = 'Loaded transcript from completed STT job.';
}
function showSttSaveSuccess(r, targetId='sttActionStatus'){
  $('sttMeta').textContent = 'Saved transcript beside selected audio:\n' + (r.transcript_path || 'saved');
  const el = targetId ? $(targetId) : null;
  const html = '<span class="ok">Transcript saved.</span> <span class="small">' + esc(r.transcript_path || '') + '</span>';
  if(el) el.innerHTML = html;
  else if($('sttActionStatus')) $('sttActionStatus').innerHTML = html;
}
function saveSttJobTranscript(path, text, jobid=''){
  if(!path || !text){ if($('sttActionStatus')) $('sttActionStatus').innerHTML='<span class="bad">No STT transcript/path available to save.</span>'; return; }
  const selected = $('sttSource') ? $('sttSource').value : '';
  const target = jobid ? 'stt-save-status-' + jobid : 'sttActionStatus';
  if($(target)) $(target).innerHTML='Saving...';
  api('/api/stt/save-transcript', {method:'POST', body:JSON.stringify({path, text})}).then(r=>{ showSttSaveSuccess(r, target); loadProfiles(); loadRefs(); loadSttSources(selected || path); }).catch(err=>{ if($(target)) $(target).innerHTML='<span class="bad">Save failed: '+esc(err)+'</span>'; });
}
function useSttAsSynthesizeReference(path='', text=''){
  const audioPath = path || ($('sttSource') ? $('sttSource').value : '') || '';
  const transcript = text || ($('sttTranscript') ? $('sttTranscript').value : '') || '';
  $('profileSelect').value = '';
  if(audioPath) $('ref').value = audioPath;
  $('refText').value = transcript;
  if($('synthRefUploadStatus')) $('synthRefUploadStatus').innerHTML = audioPath ? '<span class="ok">Loaded audio + transcript from STT.</span><br><span class="small"><code>'+esc(audioPath)+'</code></span>' : '<span class="warn">Loaded transcript from STT, but no audio path was available.</span>';
  showTab('single');
  scheduleFormStateSave();
}
function saveSttTranscript(){
  const path=$('sttSource').value || '';
  const text=$('sttTranscript').value || '';
  if(!path){ alert('Choose an audio source first.'); return; }
  if(!text.trim()){ alert('Transcript is empty.'); return; }
  api('/api/stt/save-transcript', {method:'POST', body:JSON.stringify({path,text})}).then(r=>{ showSttSaveSuccess(r, 'sttActionStatus'); loadProfiles(); loadRefs(); loadSttSources(path); }).catch(err=>{ $('sttActionStatus').innerHTML='<span class="bad">Save failed: '+esc(err)+'</span>'; });
}


function videoOptionsBody(){
  const naming = globalNamingBody();
  return Object.assign(naming, {
    format:$('videoFormat').value,
    mp3_bitrate:$('videoMp3Bitrate').value,
    trim_start:$('videoTrimStart').value,
    trim_duration:$('videoTrimDuration').value,
    sample_rate:$('videoSampleRate').value,
    channels:$('videoChannels').value,
    normalize:$('videoNormalize').checked
  });
}
function toggleVideoBitrate(){
  const isMp3 = $('videoFormat') && $('videoFormat').value === 'mp3';
  if($('videoMp3Bitrate')) $('videoMp3Bitrate').disabled = !isMp3;
}
function loadVideoIntakeStatus(){
  return api('/api/video-intake/status').then(d=>{
    if(!$('videoIntakeStatus')) return;
    const bits=[];
    if((d.video_dl_candidates||[]).length) bits.push('/home/user/video-dl runnable: '+(d.video_dl_candidates||[]).join(', '));
    else if(d.video_dl_dir_exists) bits.push('/home/user/video-dl folder present, but no recognized runnable helper');
    if(d.yt_dlp) bits.push('yt-dlp detected');
    if(d.custom_command) bits.push('custom command configured');
    const detail = esc(bits.join(', ') || 'no helper configured');
    $('videoIntakeStatus').innerHTML = d.ready
      ? '<span class="ok">URL import helper available:</span> ' + detail
      : '<span class="warn">URL import helper not ready.</span> ' + detail + '. Upload archiving/extraction still works; URL import needs a recognized <code>/home/user/video-dl</code> entrypoint, <code>yt-dlp</code>, or <code>TTS_VIDEO_DL_CMD</code>. Failed URL jobs now write helper diagnostics into the job log.';
  }).catch(err=>{ if($('videoIntakeStatus')) $('videoIntakeStatus').innerHTML='<span class="bad">Could not check video intake helpers: '+esc(err)+'</span>'; });
}
let videoSources = [];
function loadVideoSources(preferredPath=''){
  const want = preferredPath || ($('videoSourceSelect') ? $('videoSourceSelect').value : '') || '';
  return api('/api/video-intake/sources').then(data=>{
    videoSources = data.sources || [];
    const sel=$('videoSourceSelect'); if(!sel) return;
    sel.innerHTML='';
    for(const src of videoSources){
      const o=document.createElement('option');
      o.value=src.path;
      const dur = src.duration_seconds ? ` · ${Number(src.duration_seconds).toFixed(1)}s` : '';
      o.textContent=`${src.label || src.name} (${src.media_type || src.ext || 'media'}${dur})`;
      sel.appendChild(o);
    }
    if(want && Array.from(sel.options).some(o=>o.value===want)) sel.value=want;
    selectVideoSource();
  }).catch(err=>{ if($('videoActionStatus')) $('videoActionStatus').innerHTML='<span class="bad">Could not load archived sources: '+esc(err)+'</span>'; });
}
function selectVideoSource(){
  const path=$('videoSourceSelect') ? ($('videoSourceSelect').value || '') : '';
  if($('videoSourcePath')) $('videoSourcePath').textContent = path;
}
async function uploadVideoSource(){
  const file=$('videoUpload').files[0];
  if(!file){ $('videoActionStatus').innerHTML='<span class="bad">Choose a video/audio file first.</span>'; return; }
  $('videoActionStatus').textContent='Uploading and saving source media...';
  const body={filename:$('videoUploadName').value || file.name, data_base64:await fileToB64(file)};
  api('/api/video-intake/upload', {method:'POST', body:JSON.stringify(body)})
    .then(r=>{ $('videoActionStatus').innerHTML='<span class="ok">Saved source media.</span> It is archived now; extract audio separately when ready.'; lastJobsSig=''; refreshJobs(); loadVideoSources(r.uploaded_path || ''); startPoll(); })
    .catch(err=>{ $('videoActionStatus').innerHTML='<span class="bad">Could not save uploaded source: '+esc(err)+'</span>'; });
}
function importVideoUrl(){
  const url=($('videoUrl').value || '').trim();
  if(!url){ $('videoActionStatus').innerHTML='<span class="bad">Paste a URL first.</span>'; return; }
  const body={url};
  $('videoActionStatus').textContent='Queued URL import/download job. It will save the source media without extracting audio.';
  api('/api/video-intake/url', {method:'POST', body:JSON.stringify(body)})
    .then(()=>{ lastJobsSig=''; refreshJobs(); startPoll(); })
    .catch(err=>{ $('videoActionStatus').innerHTML='<span class="bad">Could not queue URL import: '+esc(err)+'</span>'; });
}
function extractVideoSource(path, statusId=''){
  if(!path){ logUiEvent('extract source refused: missing path', null, 'warn'); $('videoActionStatus').innerHTML='<span class="bad">Choose an archived source first.</span>'; setInlineStatus(statusId, '<span class="bad">Choose an archived source first.</span>'); return; }
  logUiEvent('handoff start: extract audio from source', {path});
  const body=Object.assign(videoOptionsBody(), {source_path:path});
  $('videoActionStatus').textContent='Queued audio extraction job from archived source. Watch Jobs for progress/logs.';
  setInlineStatus(statusId, '<span class="warn">Queued extraction...</span>');
  api('/api/video-intake/extract', {method:'POST', body:JSON.stringify(body)})
    .then(()=>{ logUiEvent('handoff success: extraction job queued', {path}); setInlineStatus(statusId, '<span class="ok">Queued extraction job.</span>'); lastJobsSig=''; refreshJobs(); startPoll(); })
    .catch(err=>{ logUiEvent('handoff failed: queue extraction', {path, error:String(err)}, 'error'); $('videoActionStatus').innerHTML='<span class="bad">Could not queue audio extraction: '+esc(err)+'</span>'; setInlineStatus(statusId, '<span class="bad">Could not queue extraction: '+esc(err)+'</span>'); });
}
function extractSelectedVideoSource(){
  const path=$('videoSourceSelect') ? ($('videoSourceSelect').value || '') : '';
  extractVideoSource(path);
}
function openInStt(path){
  if(!path){ logUiEvent('STT handoff refused: missing path', null, 'warn'); return; }
  logUiEvent('handoff start: send to STT', {path});
  showTab('stt');
  if($('sttActionStatus')) $('sttActionStatus').textContent='Loading audio in STT...';
  loadSttSources(path).then(()=>{
    const selected = $('sttSource') && $('sttSource').value === path;
    if($('sttActionStatus')) $('sttActionStatus').innerHTML = selected
      ? '<span class="ok">Loaded audio in STT.</span><br><span class="small"><code>'+esc(path)+'</code></span>'
      : '<span class="warn">Opened STT, but this audio was not found in the STT source picker.</span><br><span class="small"><code>'+esc(path)+'</code></span>';
    focusPane('stt');
    logUiEvent(selected ? 'handoff success: STT source selected' : 'handoff warning: STT source not found in picker', {path, selected}, selected ? 'info' : 'warn');
  }).catch(err=>{ logUiEvent('handoff failed: STT source load', {path, error:String(err)}, 'error'); if($('sttActionStatus')) $('sttActionStatus').innerHTML='<span class="bad">Could not load STT source: '+esc(err)+'</span>'; });
}
function openInAudioLab(path){
  if(!path){ logUiEvent('Audio Lab handoff refused: missing path', null, 'warn'); return; }
  logUiEvent('handoff start: open in Audio Lab', {path});
  showTab('audio');
  if($('audioLabStatus')) $('audioLabStatus').textContent='Loading audio in Audio Lab...';
  loadAudioLabSources(path).then(()=>{
    const selected = $('audioLabSource') && $('audioLabSource').value === path;
    if($('audioLabStatus')) $('audioLabStatus').innerHTML = selected
      ? '<span class="ok">Loaded audio in Audio Lab.</span><br><span class="small"><code>'+esc(path)+'</code></span>'
      : '<span class="warn">Opened Audio Lab, but this audio was not found in the source picker.</span><br><span class="small"><code>'+esc(path)+'</code></span>';
    focusPane('audio');
    logUiEvent(selected ? 'handoff success: Audio Lab source selected' : 'handoff warning: Audio Lab source not found in picker', {path, selected}, selected ? 'info' : 'warn');
  }).catch(err=>{ logUiEvent('handoff failed: Audio Lab source load', {path, error:String(err)}, 'error'); if($('audioLabStatus')) $('audioLabStatus').innerHTML='<span class="bad">Could not load Audio Lab source: '+esc(err)+'</span>'; });
}
function openInResemble(path){
  if(!path){ logUiEvent('Resemble handoff refused: missing path', null, 'warn'); return; }
  logUiEvent('handoff start: open in Resemble Enhance', {path});
  showTab('resemble');
  if($('resembleRunStatus')) $('resembleRunStatus').textContent='Loading audio in Resemble Enhance...';
  loadResembleSources(path).then(()=>{
    const selected = $('resembleSource') && $('resembleSource').value === path;
    if($('resembleRunStatus')) $('resembleRunStatus').innerHTML = selected
      ? '<span class="ok">Loaded audio in Resemble Enhance.</span><br><span class="small"><code>'+esc(path)+'</code></span>'
      : '<span class="warn">Opened Resemble Enhance, but this audio was not found in the source picker.</span><br><span class="small"><code>'+esc(path)+'</code></span>';
    focusPane('resemble');
    logUiEvent(selected ? 'handoff success: Resemble source selected' : 'handoff warning: Resemble source not found in picker', {path, selected}, selected ? 'info' : 'warn');
  }).catch(err=>{ logUiEvent('handoff failed: Resemble source load', {path, error:String(err)}, 'error'); if($('resembleRunStatus')) $('resembleRunStatus').innerHTML='<span class="bad">Could not load Resemble source: '+esc(err)+'</span>'; });
}
function openExternalTarget(path, target='system-default', statusId=''){
  if(!path){ logUiEvent('external launch refused: missing path', {target}, 'warn'); return; }
  const label = target === 'audacity' ? 'Audacity' : (target === 'containing-folder' ? 'containing folder' : 'system default app');
  setInlineStatus(statusId, '<span class="warn">Launching '+esc(label)+'...</span>');
  logUiEvent('external launch start', {target, path});
  api('/api/external-launch', {method:'POST', body:JSON.stringify({target, path})})
    .then(r=>{
      setInlineStatus(statusId, '<span class="ok">Launch requested: '+esc(r.label || label)+'.</span> <span class="small">Logged at <code>'+esc(r.log_path || '')+'</code></span>');
      logUiEvent('external launch success', {target, path, command:r.command || [], log_path:r.log_path || ''});
    })
    .catch(err=>{
      setInlineStatus(statusId, '<span class="bad">Could not launch '+esc(label)+': '+esc(err)+'</span>');
      logUiEvent('external launch failed', {target, path, error:String(err)}, 'error');
    });
}
function saveAudioAsReference(path, transcript='', statusId=''){
  if(!path){ logUiEvent('save reference refused: missing path', null, 'warn'); return; }
  logUiEvent('handoff start: save as loose reference', {path, transcript_chars:String(transcript||'').length});
  setInlineStatus(statusId, 'Saving audio as loose reference...');
  if($('refsActionStatus')) $('refsActionStatus').textContent='Saving audio as loose reference...';
  api('/api/save-ref-from-path', {method:'POST', body:JSON.stringify({path, transcript})})
    .then(r=>{
      setInlineStatus(statusId, '<span class="ok">Saved loose reference.</span>');
      showTab('refs');
      return loadRefs().then(()=>{
        if($('refsActionStatus')) $('refsActionStatus').innerHTML='<span class="ok">Saved loose reference:</span> <code>'+esc(r.path)+'</code>';
        loadSttSources(r.path);
        focusPane('refs');
        logUiEvent('handoff success: saved loose reference', {source:path, saved:r.path});
      });
    })
    .catch(err=>{
      logUiEvent('handoff failed: save loose reference', {path, error:String(err)}, 'error');
      setInlineStatus(statusId, '<span class="bad">Could not save reference: '+esc(err)+'</span>');
      if($('refsActionStatus')) $('refsActionStatus').innerHTML='<span class="bad">Could not save reference: '+esc(err)+'</span>';
    });
}
function createProfileFromAudio(path, transcript=''){
  createProfileFromLoose(path, transcript || '');
}
function extractedAudioActions(path, transcript='', key=''){
  if(!path) return '';
  const statusId = key ? 'action-menu-status-' + key : '';
  transcript = transcript || '';
  return actionMenu('Actions', [
    {section:'Use in app'},
    {label:'Send to STT', action:'open-stt', opts:{path}},
    {label:'Use as Synthesize reference', action:'set-reference', opts:{path, transcript}},
    {label:'Open in Audio Lab', action:'open-audio-lab', opts:{path}},
    {label:'Open in Resemble Enhance', action:'open-resemble', opts:{path}},
    {label:'Save as reference', action:'save-reference', opts:{path, transcript, statusid: statusId}},
    {label:'Create voice profile', action:'create-profile', opts:{path, transcript}, extraClass:'secondary pref-profile-tools'},
    {section:'Open externally'},
    {label:'Send to Audacity', action:'open-external', opts:{path, target:'audacity', statusid: statusId}},
    {label:'Open with system default app', action:'open-external', opts:{path, target:'system-default', statusid: statusId}},
    {label:'Open containing folder', action:'open-external', opts:{path, target:'containing-folder', statusid: statusId}},
  ], key);
}
function sourceMediaActions(path, downloadUrl='', key=''){
  if(!path) return '';
  const statusId = key ? 'action-menu-status-' + key : '';
  const isAudio = !!path.match(/\.(wav|mp3|flac|ogg|m4a|aac|opus)$/i);
  const items = [
    {section:'Use in app'},
    {label:'Extract audio from this source', action:'extract-video-source', opts:{path, statusid: statusId}},
  ];
  if(downloadUrl) items.push({link:true, label:'Download archived source', href:downloadUrl, download:true});
  if(isAudio){
    items.push({label:'Open audio source in Audio Lab', action:'open-audio-lab', opts:{path}});
    items.push({label:'Open audio source in Resemble Enhance', action:'open-resemble', opts:{path}});
  }
  items.push({section:'Open externally'});
  if(isAudio) items.push({label:'Send to Audacity', action:'open-external', opts:{path, target:'audacity', statusid: statusId}});
  items.push({label:'Open with system default app', action:'open-external', opts:{path, target:'system-default', statusid: statusId}});
  items.push({label:'Open containing folder', action:'open-external', opts:{path, target:'containing-folder', statusid: statusId}});
  return actionMenu('Actions', items, key);
}
function videoJobBlock(j){
  const result = j.result || {};
  const path = j.output_path || j.output || result.output_audio || '';
  const fmt = (result.output_format || (path||'').split('.').pop() || 'audio').toLowerCase();
  const sourceMedia = result.source_media || (result.kind==='video-intake-source' ? j.source_path : '') || '';
  const sourceUrl = result.source_url || '';
  const sourceLabel = sourceUrl || sourceMedia || j.source_path || '';
  const sourceLine = sourceLabel ? `<div class="small">Source: <code>${esc(String(sourceLabel).slice(0,240))}</code></div>` : '';
  if(result.kind === 'video-intake-source' || (sourceMedia && result.archived_only)){
    const dur = result.duration_seconds ? ` · duration: <code>${esc(fmtDuration(result.duration_seconds))}</code>` : '';
    const details = `<div class="small">Archived source media${result.media_type?' · type: <code>'+esc(result.media_type)+'</code>':''}${dur}. Audio was not extracted automatically.</div>`;
    return `${sourceLine}${details}${sourceMedia?sourceMediaActions(sourceMedia, result.source_download_url || '', j.id || ''):''}`;
  }
  const details = Object.keys(result).length ? `<div class="small">Extracted format: <code>${esc(fmt)}</code>${result.sample_rate?' · sample rate: <code>'+esc(String(result.sample_rate))+'</code>':''}${result.channels?' · channels: <code>'+esc(String(result.channels))+'</code>':''}${result.normalize_dynaudnorm?' · normalized with dynaudnorm':''}</div>` : '';
  const player = (path && j.audio_url) ? `<audio controls preload="none" src="${j.preview_url || j.audio_url}"></audio>${durationBadge(j.duration_seconds, false)}<br>` : '';
  const download = (path && (j.wav_url || j.audio_url)) ? ` <a download href="${j.wav_url || j.audio_url}">Download extracted ${esc(fmt)}</a>` : '';
  const sourceDownload = (sourceMedia && result.source_download_url) ? `<div class="small">Archived source: <a download href="${esc(result.source_download_url)}">download source media</a></div>` : '';
  return `${sourceLine}${details}${sourceDownload}${player}${path?extractedAudioActions(path, j.transcript || result.stt_transcript || '', j.id || '') + download:''}`;
}

let audioLabSources = [];
function loadAudioLabSources(preferredPath=''){
  const want = preferredPath || ($('audioLabSource') ? $('audioLabSource').value : '') || '';
  return api('/api/audio-lab/sources').then(data=>{
    audioLabSources = data.sources || [];
    const sel=$('audioLabSource'); if(!sel) return;
    sel.innerHTML='';
    for(const src of audioLabSources){ const o=document.createElement('option'); o.value=src.path; o.textContent=src.label; sel.appendChild(o); }
    if(want && Array.from(sel.options).some(o=>o.value===want)) sel.value=want;
    selectAudioLabSource();
  }).catch(console.warn);
}
function selectAudioLabSource(){
  const path=$('audioLabSource') ? ($('audioLabSource').value || '') : '';
  if($('audioLabSourcePath')) $('audioLabSourcePath').textContent = path;
  updateNamingSummaries();
  toggleAudioLabBitrate();
}
function toggleAudioLabBitrate(){
  const fmt = $('audioLabFormat') ? $('audioLabFormat').value : 'unchanged';
  const src = $('audioLabSource') ? ($('audioLabSource').value || '') : '';
  const srcExt = src.includes('.') ? src.split('.').pop().toLowerCase() : '';
  const isMp3 = fmt === 'mp3' || (fmt === 'unchanged' && srcExt === 'mp3');
  if($('audioLabMp3Bitrate')) $('audioLabMp3Bitrate').disabled = !isMp3;
}
function processAudioLab(){
  const path=$('audioLabSource').value || '';
  if(!path){ $('audioLabStatus').innerHTML='<span class="bad">Choose an audio source first.</span>'; return; }
  const body=Object.assign({path}, globalNamingBody(), {
    format:$('audioLabFormat').value,
    mp3_bitrate:$('audioLabMp3Bitrate').value,
    trim_start:$('audioLabTrimStart').value,
    trim_duration:$('audioLabTrimDuration').value,
    sample_rate:$('audioLabSampleRate').value,
    channels:$('audioLabChannels').value,
    normalize:$('audioLabNormalize').checked
  });
  $('audioLabStatus').textContent='Queued Audio Lab processing job. Watch Jobs for progress/logs.';
  api('/api/audio-lab/process', {method:'POST', body:JSON.stringify(body)}).then(()=>{ lastJobsSig=''; refreshJobs(); startPoll(); }).catch(err=>{ $('audioLabStatus').innerHTML='<span class="bad">Could not queue Audio Lab job: '+esc(err)+'</span>'; });
}

function renderResembleStatus(data){
  const el=$('resembleStatus');
  if(!el) return;
  const ready = !!data.ready;
  const candidates = (data.candidates || []).map(c => {
    const marker = c.exists ? '<span class="ok">available</span>' : '<span class="bad">not found</span>';
    const label = esc(c.label || c.kind || 'candidate');
    const path = c.path ? ' <code>'+esc(c.path)+'</code>' : '';
    return '<li>'+label+': '+marker+path+'</li>';
  }).join('');
  const best = (data.best_command || []).join(' ');
  const gl = data.git_lfs || {};
  const glStatus = gl.available ? '<span class="ok">available</span>' : '<span class="bad">missing</span>';
  const glMsg = gl.message ? '<div class="small">Git LFS: '+glStatus+' — '+esc(gl.message)+'</div>' : '<div class="small">Git LFS: '+glStatus+'</div>';
  el.innerHTML = (ready ? '<span class="ok">Resemble Enhance command detected.</span>' : '<span class="warn">Resemble Enhance is not installed/detected yet.</span>') +
    '<div class="small">Root: <code>'+esc(data.root || '')+'</code></div>' +
    '<div class="small">Installer: <code>'+esc(data.installer || '')+'</code> '+(data.installer_exists ? '<span class="ok">found</span>' : '<span class="bad">missing</span>')+'</div>' +
    '<div class="small">Env Python: '+(data.env_python ? '<code>'+esc(data.env_python)+'</code>' : '<span class="warn">not detected</span>')+'</div>' +
    '<div class="small">Env bin PATH prefix: '+(data.env_bin ? '<code>'+esc(data.env_bin)+'</code>' : '<span class="warn">not detected</span>')+'</div>' +
    '<div class="small">Conda: '+(data.conda ? '<code>'+esc(data.conda)+'</code>' : '<span class="warn">not detected; venv fallback available</span>')+'</div>' +
    glMsg +
    (best ? '<div class="small">Best command: <code>'+esc(best)+'</code></div>' : '') +
    (candidates ? '<ul class="small">'+candidates+'</ul>' : '');
}
function loadResembleStatus(){
  return api('/api/resemble/status')
    .then(data=>{ renderResembleStatus(data); return data; })
    .catch(err=>{ const el=$('resembleStatus'); if(el) el.innerHTML='<span class="bad">Could not check Resemble Enhance status: '+esc(err)+'</span>'; });
}
function openJobsButtonHtml(){
  return ' <button class="mini secondary" type="button" onclick="showTab(\'jobs\')">Open Jobs</button>';
}
function queuedJobStatus(label, job){
  const jobId = job && job.id ? ' Job ID: <code>'+esc(job.id)+'</code>.' : '';
  return '<span class="warn">Queued '+esc(label)+' job.'+jobId+' Status and full logs are in Jobs.</span>'+openJobsButtonHtml();
}
function installResembleEnhance(){
  const mode = readFieldValue('resembleInstallMode', 'auto');
  const st=$('resembleActionStatus');
  if(st) st.innerHTML='<span class="warn">Queueing Resemble Enhance install/repair job...</span>';
  logUiEvent('resemble install clicked', {mode});
  api('/api/setup/resemble-enhance', {method:'POST', body:JSON.stringify({mode})})
    .then(r=>{ if(st) st.innerHTML=queuedJobStatus('Resemble Enhance install/repair', r.job || r); lastJobsSig=''; refreshJobs(); startPoll(); setTimeout(loadResembleStatus, 1000); })
    .catch(err=>{ if(st) st.innerHTML='<span class="bad">Could not queue Resemble Enhance setup: '+esc(err)+'</span>'; logUiEvent('resemble install queue failed', {error:String(err)}); });
}
function repairResembleGitLfs(){
  const st=$('resembleActionStatus') || $('maintResembleStatus');
  if(st) st.innerHTML='<span class="warn">Queueing Resemble Git LFS repair job...</span>';
  logUiEvent('resemble git-lfs repair clicked', {});
  api('/api/setup/resemble-git-lfs', {method:'POST', body:JSON.stringify({})})
    .then(r=>{ if(st) st.innerHTML=queuedJobStatus('Resemble Git LFS repair', r.job || r); lastJobsSig=''; refreshJobs(); startPoll(); setTimeout(()=>{ loadResembleStatus(); maintenanceCheckResemble(); }, 1000); })
    .catch(err=>{ if(st) st.innerHTML='<span class="bad">Could not queue Git LFS repair: '+esc(err)+'</span>'; logUiEvent('resemble git-lfs repair queue failed', {error:String(err)}, 'error'); });
}

let resembleSources = [];
let resembleSourceReady = false;
let resembleSourcePending = false;
function setResembleBusy(busy, message=''){
  resembleSourcePending = !!busy;
  const ids=['resembleDenoiseButton','resembleEnhanceButton','resembleRefreshButton','resembleUploadButton'];
  for(const id of ids){ const el=$(id); if(el) el.disabled=!!busy; }
  if(message && $('resembleCurrentSource')) $('resembleCurrentSource').innerHTML=message;
}
function resembleSelectedSourceMeta(){
  const path=$('resembleSource') ? ($('resembleSource').value || '') : '';
  if(!path) return null;
  return resembleSources.find(s=>s.path===path) || {path, label:path.split('/').pop()};
}
function renderResembleCurrentSource(){
  const meta = resembleSelectedSourceMeta();
  const el=$('resembleCurrentSource');
  if(!el) return;
  if(resembleSourcePending){ return; }
  if(!meta){
    resembleSourceReady = false;
    el.innerHTML='Current Resemble source: <span class="bad">none selected</span>';
    return;
  }
  resembleSourceReady = true;
  const dur = (meta.duration_seconds !== undefined && meta.duration_seconds !== null) ? ' · duration: <b>'+esc(fmtDur(meta.duration_seconds))+'</b>' : '';
  const note = (meta.duration_seconds && Number(meta.duration_seconds) > 60) ? '<div class="small warn">Long source selected. Denoise is lighter; Enhance may run out of VRAM on smaller GPUs. CPU may be safer but slower.</div>' : '';
  el.innerHTML='Current Resemble source: <b>'+esc(meta.label || meta.path.split('/').pop())+'</b>'+dur+note;
}
function loadResembleSources(preferredPath=''){
  const want = preferredPath || ($('resembleSource') ? $('resembleSource').value : '') || '';
  setResembleBusy(true, 'Current Resemble source: <span class="warn">refreshing source list...</span>');
  return api('/api/resemble/sources').then(data=>{
    resembleSources = data.sources || [];
    const sel=$('resembleSource'); if(!sel) return;
    sel.innerHTML='';
    for(const src of resembleSources){ const o=document.createElement('option'); o.value=src.path; o.textContent=src.label; sel.appendChild(o); }
    if(want && Array.from(sel.options).some(o=>o.value===want)) sel.value=want;
    else if(sel.options.length) sel.selectedIndex = 0;
    resembleSourcePending = false;
    selectResembleSource();
    setResembleBusy(false);
    renderResembleCurrentSource();
    return data;
  }).catch(err=>{ setResembleBusy(false); const st=$('resembleRunStatus'); if(st) st.innerHTML='<span class="bad">Could not load Resemble sources: '+esc(err)+'</span>'; logUiEvent('resemble sources failed', {error:String(err)}, 'error'); renderResembleCurrentSource(); });
}
function selectResembleSource(){
  const path=$('resembleSource') ? ($('resembleSource').value || '') : '';
  if($('resembleSourcePath')) $('resembleSourcePath').textContent = path;
  resembleSourceReady = !!path && !resembleSourcePending;
  renderResembleCurrentSource();
}
function uploadResembleInput(){
  const inp=$('resembleUploadFile');
  const st=$('resembleUploadStatus');
  if(!inp || !inp.files || !inp.files.length){ if(st) st.innerHTML='<span class="bad">Choose an audio file first.</span>'; return; }
  const file=inp.files[0];
  const wanted=(readFieldValue('resembleUploadName','').trim() || file.name || 'resemble-input.wav');
  setResembleBusy(true, 'Current Resemble source: <span class="warn">uploading and selecting new source...</span>');
  if(st) st.innerHTML='Reading upload... Denoise/Enhance are disabled until the uploaded file is selected.';
  logUiEvent('resemble upload start', {name:file.name, size:file.size});
  fileToB64(file).then(b64=>api('/api/resemble/upload', {method:'POST', body:JSON.stringify({filename:wanted, data_base64:b64})}))
    .then(r=>{
      if(st) st.innerHTML='<span class="warn">Uploaded Resemble input. Refreshing sources and selecting it...</span> <code>'+esc(r.path)+'</code>';
      logUiEvent('resemble upload success', {path:r.path, size:r.size, duration_seconds:r.duration_seconds});
      return loadResembleSources(r.path).then(()=>{
        if(st) st.innerHTML='<span class="ok">Uploaded and selected for Resemble:</span> <code>'+esc(r.path)+'</code>';
        if($('resembleRunStatus')) $('resembleRunStatus').innerHTML='<span class="ok">Ready for Resemble: '+esc(r.name || r.path.split('/').pop())+' '+(r.duration_seconds ? '('+esc(fmtDur(r.duration_seconds))+')' : '')+'</span>';
      });
    })
    .catch(err=>{ setResembleBusy(false); if(st) st.innerHTML='<span class="bad">Upload failed: '+esc(err)+'</span>'; logUiEvent('resemble upload failed', {error:String(err)}, 'error'); renderResembleCurrentSource(); });
}
function runResembleEnhance(mode){
  if(resembleSourcePending || !resembleSourceReady){ const st=$('resembleRunStatus'); if(st) st.innerHTML='<span class="bad">Resemble source is still uploading/refreshing. Wait for “Ready” before starting a job.</span>'; return; }
  const meta = resembleSelectedSourceMeta();
  const source=meta ? meta.path : '';
  const st=$('resembleRunStatus');
  if(!source){ if(st) st.innerHTML='<span class="bad">Choose a Resemble input source first.</span>'; return; }
  const label = mode === 'denoise' ? 'denoise-only' : 'enhance';
  const device=readFieldValue('resembleDevice', 'auto');
  const body=Object.assign({path:source, mode, device, source_duration_seconds: meta.duration_seconds || null, source_label: meta.label || ''}, globalNamingBody());
  const dur = (meta.duration_seconds !== undefined && meta.duration_seconds !== null) ? ' Duration: '+fmtDur(meta.duration_seconds)+'.' : '';
  const longWarn = (mode === 'enhance' && meta.duration_seconds && Number(meta.duration_seconds) > 60) ? ' <span class="warn">Long Enhance jobs may run out of VRAM; CPU may be safer but slower.</span>' : '';
  if(st) st.innerHTML='<span class="warn">Queued Resemble '+esc(label)+' job for '+esc(meta.label || source.split('/').pop())+'.'+esc(dur)+'</span>'+longWarn+openJobsButtonHtml();
  logUiEvent('resemble run clicked', {mode, source, device, duration_seconds: meta.duration_seconds || null, label: meta.label || ''});
  api('/api/resemble/process', {method:'POST', body:JSON.stringify(body)})
    .then(r=>{ if(st) st.innerHTML=queuedJobStatus('Resemble '+label, r.job || r)+' <span class="small">Source: '+esc(meta.label || source.split('/').pop())+'.'+esc(dur)+'</span>'; lastJobsSig=''; refreshJobs(); startPoll(); })
    .catch(err=>{ if(st) st.innerHTML='<span class="bad">Could not queue Resemble job: '+esc(err)+'</span>'; logUiEvent('resemble run queue failed', {mode, source, error:String(err)}, 'error'); });
}
function resembleJobBlock(j){
  const result = j.result || {};
  const mode = result.mode || j.role || '';
  const src = result.source_audio || j.source_path || '';
  const raw = result.raw_output || '';
  const fmt = result.output_format || ((j.output_path||j.output||'').split('.').pop() || 'audio');
  const work = result.work_dir || '';
  const path = j.output_path || j.output || result.output_audio || '';
  const sourceLabel = result.source_label || (src ? src.split('/').pop() : '');
  const sourceDur = result.source_duration_seconds ? ` · source duration: <code>${esc(fmtDuration(result.source_duration_seconds))}</code>` : '';
  const summary = sourceLabel ? `<div class="small">Source label: <code>${esc(String(sourceLabel).slice(0,240))}</code>${sourceDur}</div>` : '';
  const actions = path ? `${extractedAudioActions(path, '', 'resemble-'+(j.id || ''))}${actionButton('Delete Resemble output', 'delete-output', {path, name: path.split('/').pop()}, 'danger pref-delete')}` : '';
  const player = (j.audio_url && path) ? `<audio controls preload="none" src="${j.preview_url || j.audio_url}"></audio>${durationBadge(j.duration_seconds, false)}<br>${actions}<a download href="${j.wav_url || j.audio_url}">download ${esc(String(fmt).toLowerCase())}</a><br>${metadataBlock(j)}` : '';
  return `<div class="small">Mode: <code>${esc(mode)}</code> · Output format: <code>${esc(String(fmt))}</code></div>` +
    summary +
    (src?`<div class="small">Source: <code>${esc(String(src).slice(0,240))}</code></div>`:'') +
    (raw?`<div class="small">Raw Resemble output: <code>${esc(String(raw).slice(0,240))}</code></div>`:'') +
    player +
    (work?`<details class="pref-metadata"><summary>Resemble work directory</summary><code>${esc(work)}</code></details>`:'');
}

function loadAll(){ toggleVideoBitrate(); applyLayoutPrefs(); renderMaintenance(); return Promise.all([loadProfiles(), loadRefs(), loadOutputs(true), refreshJobs(), loadSttStatus(), loadSttSources(), loadAudioLabSources(), loadVideoIntakeStatus(), loadVideoSources(), loadResembleStatus(), loadResembleSources()]).then(r=>{ renderMaintenance(); maintenanceCheckStack(); maintenanceCheckHfToken(); maintenanceCheckWhisper(); maintenanceCheckVideoImporter(); maintenanceCheckResemble(); return r; }); }
function startPoll(){
  if(poll) return;
  poll=setInterval(async ()=>{
    const active = await refreshJobs();
    if(!active){
      stopPoll();
      lastOutputsSig='';
      await loadOutputs(true);
      await loadVideoSources();
      await refreshJobs();
    }
  }, 2500);
}
api('/api/meta').then(setupEngines).then(loadAll).then(restoreFormState).then(restoreTabFromHash).catch(alert);
</script>
</body>
</html>
'''


def restart_process_soon(delay: float = 0.7) -> None:
    time.sleep(delay)
    # Refresh LD_LIBRARY_PATH for newly installed Whisper CUDA wheels before re-execing.
    libs = whisper_nvidia_lib_dirs()
    if libs:
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = ":".join(libs + ([existing] if existing else []))
    os.execv(sys.executable, [sys.executable] + sys.argv)


class Handler(BaseHTTPRequestHandler):
    server_version = f"TTSLabWebUI/{VERSION}"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")

    def send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_text(self, text: str, content_type: str = "text/html; charset=utf-8") -> None:
        raw = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path: Path, content_type: str | None = None, download_name: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        ctype = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        size = path.stat().st_size
        disposition = "inline" if ctype.startswith("audio/") else "attachment"
        range_header = self.headers.get("Range") if ctype.startswith("audio/") else None
        start = 0
        end = size - 1
        status = 200
        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = 206

        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Disposition", f'{disposition}; filename="{download_name or path.name}"')
        if ctype.startswith("audio/"):
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/" or path == "/index.html":
                self.send_text(INDEX_HTML)
            elif path == "/api/meta":
                self.send_json({"version": VERSION, "lab": str(LAB), "launcher": str(LAUNCHER), "default_ref": str(DEFAULT_REF), "engines": ENGINE_META})
            elif path == "/api/stack-status":
                self.send_json(stack_status_payload())
            elif path == "/api/profiles":
                self.send_json({"profiles": profiles_payload()})
            elif path == "/api/refs":
                self.send_json({"refs": loose_refs_payload()})
            elif path == "/api/outputs":
                self.send_json({"outputs": outputs_payload()})
            elif path == "/api/jobs":
                self.send_json({"jobs": JOBS.list_recent()})
            elif path == "/api/state":
                self.send_json({"state": read_webui_state(), "path": str(WEBUI_STATE)})
            elif path == "/api/stt/status":
                self.send_json(whisper_status_payload())
            elif path == "/api/stt/sources":
                self.send_json({"sources": stt_sources_payload()})
            elif path == "/api/audio-lab/sources":
                self.send_json({"sources": audio_lab_sources_payload()})
            elif path == "/api/video-intake/status":
                self.send_json(video_intake_status_payload())
            elif path == "/api/video-intake/sources":
                self.send_json({"sources": video_source_media_payload()})
            elif path == "/api/external-launch/status":
                self.send_json(external_command_status())
            elif path == "/api/resemble/status":
                self.send_json(resemble_status_payload())
            elif path == "/api/resemble/sources":
                self.send_json({"sources": resemble_sources_payload()})
            elif path == "/api/hf-token/status":
                self.send_json(hf_token_status_payload())
            elif path.startswith("/api/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                job = JOBS.get(job_id)
                self.send_json({"job": job.public()} if job else {"error": "not found"}, 200 if job else 404)
            elif path.startswith("/preview-audio/"):
                rel = unquote(path[len("/preview-audio/"):]).strip("/")
                target = (OUT_DIR / rel).resolve()
                if not inside(target, OUT_DIR):
                    self.send_json({"error": "bad path"}, 400)
                else:
                    preview = ensure_mp3_preview(target)
                    if preview and preview.exists():
                        self.send_file(preview, "audio/mpeg", download_name=target.with_suffix(".mp3").name)
                    else:
                        self.send_file(target, mimetypes.guess_type(str(target))[0] or "audio/wav")
            elif path.startswith("/audio/"):
                rel = unquote(path[len("/audio/"):]).strip("/")
                target = (OUT_DIR / rel).resolve()
                if not inside(target, OUT_DIR):
                    self.send_json({"error": "bad path"}, 400)
                else:
                    self.send_file(target, mimetypes.guess_type(str(target))[0] or "audio/wav")
            elif path.startswith("/ref-audio/"):
                rel = safe_filename(unquote(path[len("/ref-audio/"):]).strip("/"), "reference.wav")
                target = (REF_DIR / rel).resolve()
                if not inside(target, REF_DIR):
                    self.send_json({"error": "bad path"}, 400)
                else:
                    self.send_file(target, mimetypes.guess_type(str(target))[0] or "audio/wav")
            elif path.startswith("/audio-lab-waveform/"):
                rel = safe_filename(unquote(path[len("/audio-lab-waveform/"):]).strip("/"), "waveform.svg")
                target = (AUDIO_LAB_DIR / rel).resolve()
                if not inside(target, AUDIO_LAB_DIR):
                    self.send_json({"error": "bad path"}, 400)
                else:
                    self.send_file(target, "image/svg+xml; charset=utf-8")
            elif path.startswith("/profile-audio/"):
                rel = unquote(path[len("/profile-audio/"):]).strip("/")
                target = (PROFILE_DIR / rel).resolve()
                if not inside(target, PROFILE_DIR):
                    self.send_json({"error": "bad path"}, 400)
                else:
                    self.send_file(target, mimetypes.guess_type(str(target))[0] or "audio/wav")
            elif path.startswith("/profile-zip/"):
                slug_zip = safe_filename(unquote(path[len("/profile-zip/"):]).strip("/"), "profile.zip")
                slug = slug_zip[:-4] if slug_zip.endswith(".zip") else slug_zip
                profile_dir = (PROFILE_DIR / slug).resolve()
                if not inside(profile_dir, PROFILE_DIR) or not profile_dir.exists():
                    self.send_json({"error": "profile not found"}, 404)
                    return
                zip_path = OUT_DIR / f"{slug}_voice_profile.zip"
                with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for name in ("voice-profile.json", "audio.wav", "audio.mp3", "audio.flac", "audio.m4a", "audio.ogg", "transcript.txt"):
                        p = profile_dir / name
                        if p.exists():
                            zf.write(p, p.name)
                self.send_file(zip_path, "application/zip", download_name=f"{slug}.zip")
            elif path.startswith("/manifest/"):
                rel = unquote(path[len("/manifest/"):]).strip("/")
                candidates = list(OUT_DIR.rglob(rel))
                self.send_file(candidates[0], "application/json; charset=utf-8") if candidates else self.send_json({"error": "manifest not found"}, 404)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            body = read_json_body(self)
            if path == "/api/state":
                self.send_json({"state": write_webui_state(body), "path": str(WEBUI_STATE)})
            elif path == "/api/state/clear":
                self.send_json({"state": clear_webui_state(), "path": str(WEBUI_STATE)})
            elif path == "/api/generate":
                profile_slug = str(body.get("profile", "")).strip()
                if profile_slug:
                    p = profile_manifest(PROFILE_DIR / profile_slug)
                    if not p:
                        raise ValueError(f"Unknown profile: {profile_slug}")
                    body.setdefault("ref", p["audio_path"])
                    if not str(body.get("ref_text", "")).strip():
                        body["ref_text"] = p.get("transcript", "")
                job = Job(id=uuid.uuid4().hex, kind="single")
                JOBS.add(job, body)
                self.send_json({"job": job.public()})
            elif path == "/api/batch":
                job = Job(id=uuid.uuid4().hex, kind="batch")
                JOBS.add(job, body)
                self.send_json({"job": job.public()})
            elif path == "/api/hf-token/save":
                self.send_json(save_hf_token(str(body.get("token", ""))))
            elif path == "/api/hf-token/test":
                self.send_json(test_hf_token())
            elif path == "/api/hf-token/forget":
                self.send_json(forget_hf_token())
            elif path == "/api/stt/upload":
                filename = safe_filename(str(body.get("filename", "stt_audio.wav")), "stt_audio.wav")
                if Path(filename).suffix.lower() not in AUDIO_EXTS:
                    filename += ".wav"
                data = decode_b64(str(body.get("data_base64", "")))
                ensure_dirs()
                target = STT_UPLOAD_DIR / filename
                target.write_bytes(data)
                self.send_json({"path": str(target), "name": target.name, "size": target.stat().st_size, "duration_seconds": audio_duration_seconds(target)})
            elif path == "/api/stt/transcribe":
                job = Job(id=uuid.uuid4().hex, kind="stt")
                JOBS.add(job, body)
                self.send_json({"job": job.public()})
            elif path == "/api/stt/save-transcript":
                self.send_json(save_stt_transcript(str(body.get("path", "")), str(body.get("text", ""))))
            elif path == "/api/jobs/cancel":
                self.send_json(JOBS.cancel(str(body.get("job_id", ""))))
            elif path == "/api/audio-lab/process":
                job = Job(id=uuid.uuid4().hex, kind="audio")
                JOBS.add(job, body)
                self.send_json({"job": job.public()})
            elif path == "/api/video-intake/upload":
                filename = safe_filename(str(body.get("filename", "uploaded_video.mp4")), "uploaded_video.mp4")
                if Path(filename).suffix.lower() not in MEDIA_EXTS:
                    filename += ".mp4"
                data = decode_b64(str(body.get("data_base64", "")))
                ensure_dirs()
                target = VIDEO_UPLOAD_DIR / filename
                if target.exists():
                    target = next_versioned_path(target, always_version=False)
                target.write_bytes(data)
                payload = dict(body)
                payload.pop("data_base64", None)
                payload["action"] = "archive_upload"
                payload["source_type"] = "upload"
                payload["uploaded_path"] = str(target)
                payload["original_name"] = filename
                job = Job(id=uuid.uuid4().hex, kind="video")
                JOBS.add(job, payload)
                self.send_json({"job": job.public(), "uploaded_path": str(target), "name": target.name, "size": target.stat().st_size})
            elif path == "/api/video-intake/url":
                payload = dict(body)
                payload["action"] = "import_url"
                payload["source_type"] = "url"
                job = Job(id=uuid.uuid4().hex, kind="video")
                JOBS.add(job, payload)
                self.send_json({"job": job.public()})
            elif path == "/api/video-intake/extract":
                payload = dict(body)
                payload["action"] = "extract"
                job = Job(id=uuid.uuid4().hex, kind="video")
                JOBS.add(job, payload)
                self.send_json({"job": job.public()})
            elif path == "/api/save-ref-from-path":
                self.send_json(save_reference_from_path(str(body.get("path", "")), str(body.get("name", "")), str(body.get("transcript", ""))))
            elif path == "/api/stt/test-gpu":
                job = Job(id=uuid.uuid4().hex, kind="setup")
                payload = dict(body)
                payload["action"] = "whisper-gpu-test"
                JOBS.add(job, payload)
                self.send_json({"job": job.public()})
            elif path == "/api/setup/whisper-cuda":
                job = Job(id=uuid.uuid4().hex, kind="setup")
                JOBS.add(job, {"action": "whisper-cuda"})
                self.send_json({"job": job.public()})
            elif path == "/api/setup/resemble-enhance":
                job = Job(id=uuid.uuid4().hex, kind="setup")
                payload = dict(body)
                payload["action"] = "resemble-enhance"
                JOBS.add(job, payload)
                self.send_json({"job": job.public()})
            elif path == "/api/setup/resemble-git-lfs":
                job = Job(id=uuid.uuid4().hex, kind="setup")
                payload = dict(body)
                payload["action"] = "resemble-git-lfs"
                JOBS.add(job, payload)
                self.send_json({"job": job.public()})
            elif path == "/api/resemble/upload":
                filename = safe_filename(str(body.get("filename", "resemble_input.wav")), "resemble_input.wav")
                if Path(filename).suffix.lower() not in AUDIO_EXTS:
                    filename += ".wav"
                data = decode_b64(str(body.get("data_base64", "")))
                ensure_dirs()
                target = RESEMBLE_INPUT_DIR / filename
                if target.exists():
                    target = next_versioned_path(target, always_version=False)
                target.write_bytes(data)
                self.send_json({"path": str(target), "name": target.name, "size": target.stat().st_size, "duration_seconds": audio_duration_seconds(target)})
            elif path == "/api/resemble/process":
                job = Job(id=uuid.uuid4().hex, kind="resemble")
                payload = dict(body)
                JOBS.add(job, payload)
                self.send_json({"job": job.public()})
            elif path == "/api/external-launch":
                self.send_json(launch_external_target(str(body.get("target", "system-default")), str(body.get("path", ""))))
            elif path == "/api/restart":
                self.send_json({"ok": True, "message": "Restarting Web UI."})
                threading.Thread(target=restart_process_soon, daemon=True).start()
            elif path == "/api/upload-ref":
                filename = safe_filename(str(body.get("filename", "reference.wav")), "reference.wav")
                if Path(filename).suffix.lower() not in AUDIO_EXTS:
                    filename += ".wav"
                data = decode_b64(str(body.get("data_base64", "")))
                ensure_dirs()
                target = REF_DIR / filename
                target.write_bytes(data)
                transcript = str(body.get("transcript_text", "")).strip()
                transcript_path = ""
                if transcript:
                    tpath = target.with_suffix(".txt")
                    tpath.write_text(transcript + "\n", encoding="utf-8")
                    transcript_path = str(tpath)
                self.send_json({"path": str(target), "name": target.name, "size": target.stat().st_size, "transcript": transcript, "transcript_path": transcript_path, "duration_seconds": audio_duration_seconds(target)})
            elif path == "/api/create-profile":
                audio_bytes = decode_b64(str(body.get("audio_base64", ""))) if body.get("audio_base64") else None
                transcript_bytes = decode_b64(str(body.get("transcript_base64", ""))) if body.get("transcript_base64") else None
                profile = create_profile(
                    name=str(body.get("name", "")),
                    audio_bytes=audio_bytes,
                    audio_filename=str(body.get("audio_filename", "audio.wav")),
                    source_audio_path=str(body.get("source_audio_path", "")),
                    transcript_text=str(body.get("transcript_text", "")),
                    transcript_bytes=transcript_bytes,
                    transcript_filename=str(body.get("transcript_filename", "transcript.txt")),
                    speaker=str(body.get("speaker", "")),
                    style=str(body.get("style", "")),
                    notes=str(body.get("notes", "")),
                    source=str(body.get("source", "manual")),
                )
                self.send_json({"profile": profile})
            elif path == "/api/import-profile-zip":
                profile = import_profile_zip(decode_b64(str(body.get("zip_base64", ""))))
                self.send_json({"profile": profile})
            elif path == "/api/delete-profile":
                self.send_json(delete_profile(str(body.get("slug", ""))))
            elif path == "/api/promote-output":
                src = safe_existing_path(str(body.get("path", "")), [OUT_DIR])
                meta = read_output_sidecar(src)
                name = str(body.get("name") or meta.get("role") or src.stem)
                transcript = str(meta.get("text", ""))
                profile = create_profile(
                    name=name,
                    source_audio_path=str(src),
                    transcript_text=transcript,
                    speaker=str(body.get("speaker", meta.get("role", ""))),
                    style=str(body.get("style", "generated output - explicit promotion")),
                    notes=str(body.get("notes", "Promoted from generated output. Beware clone-of-clone artifacts.")),
                    source="generated-output-explicit-promotion",
                )
                # mark source sidecar as promoted
                sidecar = src.with_suffix(src.suffix + ".json")
                if sidecar.exists():
                    meta["promoted_to_profile"] = True
                    meta["promoted_profile_slug"] = profile.get("slug")
                    sidecar.write_text(json.dumps(meta, indent=2), encoding="utf-8")
                self.send_json({"profile": profile})
            elif path == "/api/delete-output":
                self.send_json(delete_output_artifacts(str(body.get("path", ""))))
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)


def bootstrap_default_profile() -> None:
    ensure_dirs()
    if DEFAULT_REF.exists() and not any(PROFILE_DIR.iterdir()):
        transcript = read_text_file_if_exists(companion_transcript(DEFAULT_REF))
        try:
            create_profile(
                name="Default Voice Reference",
                source_audio_path=str(DEFAULT_REF),
                transcript_text=transcript,
                speaker="",
                style="default imported reference",
                notes="Auto-created from /home/user/tts-lab/references/voice_ref.wav",
                source="bootstrap-default-ref",
            )
        except Exception as exc:
            print(f"WARNING: could not bootstrap default profile: {exc}")


def main() -> None:
    if not LAUNCHER.exists():
        print(f"WARNING: launcher not found: {LAUNCHER}")
    ensure_dirs()
    bootstrap_default_profile()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"TTS Lab Web UI {VERSION} running at http://{HOST}:{PORT}")
    print(f"Launcher: {LAUNCHER}")
    print(f"Profiles: {PROFILE_DIR}")
    print("Press Ctrl+C to stop.")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
