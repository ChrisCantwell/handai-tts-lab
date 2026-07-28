#!/usr/bin/env python3
"""Read-only diagnostics for the machine-local Chatterbox-Turbo stack.

This script does not modify the launcher, conda environment, models, or outputs.
It reports enough information to wire v0.97 controls to the actual installed
runtime instead of assuming the repository's external launcher implementation.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

LAB = Path(os.environ.get("TTS_LAB", "/home/user/tts-lab"))
LAUNCHER = LAB / "tts-lab.sh"
ENGINE_ROOT = LAB / "engines" / "chatterbox"
CONDA_ROOT = Path(os.environ.get("CONDA_ROOT", str(Path.home() / "miniconda3")))
ENV_PYTHON = CONDA_ROOT / "envs" / "tts-chatterbox" / "bin" / "python"

SENSITIVE = re.compile(r"(?i)(token|password|secret|api[_-]?key)\s*=\s*([^\s]+)")
INTERESTING = re.compile(
    r"(?i)(chatterbox|tts-chatterbox|synth|temperature|top[_-]?p|top[_-]?k|"
    r"repetition[_-]?penalty|min[_-]?p|seed|normalize|python)"
)


def heading(text: str) -> None:
    print("\n" + "=" * 78)
    print(text)
    print("=" * 78)


def redact(text: str) -> str:
    return SENSITIVE.sub(lambda m: f"{m.group(1)}=<redacted>", text)


def file_info(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "exists": True,
            "executable": os.access(path, os.X_OK),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
        }
    except OSError:
        return {"path": str(path), "exists": False, "executable": False}


def launcher_excerpt() -> None:
    heading("Machine-local launcher")
    print(json.dumps(file_info(LAUNCHER), indent=2))
    if not LAUNCHER.exists():
        return
    try:
        lines = LAUNCHER.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        print(f"Could not read launcher: {exc}")
        return
    matches = [(i, redact(line.rstrip())) for i, line in enumerate(lines, start=1) if INTERESTING.search(line)]
    print(f"Launcher total lines: {len(lines)}")
    print(f"Relevant lines: {len(matches)}")
    for number, line in matches[:240]:
        print(f"{number:04d}: {line}")
    if len(matches) > 240:
        print(f"... {len(matches) - 240} additional matching lines omitted")


def engine_listing() -> None:
    heading("Chatterbox engine files")
    print(json.dumps(file_info(ENGINE_ROOT), indent=2))
    if not ENGINE_ROOT.exists():
        return
    rows: list[dict[str, Any]] = []
    for path in sorted(ENGINE_ROOT.rglob("*")):
        try:
            if path.is_file():
                rows.append({
                    "path": str(path.relative_to(ENGINE_ROOT)),
                    "size": path.stat().st_size,
                    "executable": os.access(path, os.X_OK),
                })
        except OSError:
            continue
        if len(rows) >= 240:
            break
    print(json.dumps(rows, indent=2))


def environment_probe() -> None:
    heading("tts-chatterbox Python environment")
    print(json.dumps(file_info(ENV_PYTHON), indent=2))
    if not ENV_PYTHON.exists():
        print("Expected conda environment Python was not found.")
        return

    probe = r'''
from __future__ import annotations
import importlib
import inspect
import json
import platform
import sys

result = {
    "python": sys.executable,
    "python_version": sys.version,
    "platform": platform.platform(),
    "candidates": [],
}

for module_name, class_name in (
    ("chatterbox.tts_turbo", "ChatterboxTurboTTS"),
    ("chatterbox.tts", "ChatterboxTTS"),
    ("chatterbox.mtl_tts", "ChatterboxMultilingualTTS"),
):
    item = {"module": module_name, "class": class_name}
    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        item.update({
            "available": True,
            "module_file": getattr(module, "__file__", ""),
            "class_module": getattr(cls, "__module__", ""),
            "generate_signature": str(inspect.signature(cls.generate)),
            "from_pretrained_signature": str(inspect.signature(cls.from_pretrained)) if hasattr(cls, "from_pretrained") else "",
        })
        try:
            source = inspect.getsource(cls.generate)
            interesting = []
            for number, line in enumerate(source.splitlines(), start=1):
                if any(term in line.lower() for term in (
                    "temperature", "top_p", "top_k", "repetition_penalty",
                    "min_p", "seed", "normalize", "cfg_weight", "exaggeration",
                )):
                    interesting.append(f"{number:03d}: {line.rstrip()}")
            item["generate_relevant_source"] = interesting[:120]
        except Exception as exc:
            item["source_error"] = str(exc)
    except Exception as exc:
        item.update({"available": False, "error": f"{type(exc).__name__}: {exc}"})
    result["candidates"].append(item)

for package in ("chatterbox", "torch", "torchaudio", "transformers"):
    try:
        module = importlib.import_module(package)
        result.setdefault("versions", {})[package] = getattr(module, "__version__", "unknown")
    except Exception as exc:
        result.setdefault("versions", {})[package] = f"unavailable: {type(exc).__name__}: {exc}"

try:
    import torch
    result["cuda"] = {
        "available": bool(torch.cuda.is_available()),
        "device_count": int(torch.cuda.device_count()),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "",
        "allocated_bytes": int(torch.cuda.memory_allocated(0)) if torch.cuda.is_available() else 0,
        "reserved_bytes": int(torch.cuda.memory_reserved(0)) if torch.cuda.is_available() else 0,
    }
except Exception as exc:
    result["cuda"] = {"error": f"{type(exc).__name__}: {exc}"}

print(json.dumps(result, indent=2, default=str))
'''
    try:
        proc = subprocess.run(
            [str(ENV_PYTHON), "-c", probe],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            env=os.environ.copy(),
        )
    except Exception as exc:
        print(f"Could not run environment probe: {type(exc).__name__}: {exc}")
        return
    print(f"Probe return code: {proc.returncode}")
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print("\nProbe stderr:")
        print(redact(proc.stderr.strip()[-12000:]))


def main() -> int:
    heading("HandAI TTS Lab v0.97 Chatterbox-Turbo runtime inspection")
    print(f"Repository inspector: {Path(__file__).resolve()}")
    print(f"TTS_LAB: {LAB}")
    launcher_excerpt()
    engine_listing()
    environment_probe()
    heading("Inspection complete")
    print("No files or environments were modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
