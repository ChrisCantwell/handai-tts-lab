#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

: "${TTS_AI_STUDIO_BRIDGE_TOKEN:?Set TTS_AI_STUDIO_BRIDGE_TOKEN before starting the bridge}"

export TTS_LAB="${TTS_LAB:-/home/user/tts-lab}"
export TTS_WEBUI_BASE="${TTS_WEBUI_BASE:-http://127.0.0.1:7870}"
export TTS_AI_STUDIO_BRIDGE_HOST="${TTS_AI_STUDIO_BRIDGE_HOST:-127.0.0.1}"
export TTS_AI_STUDIO_BRIDGE_PORT="${TTS_AI_STUDIO_BRIDGE_PORT:-7871}"
export TTS_AI_STUDIO_BRIDGE_ALLOWED_ORIGINS="${TTS_AI_STUDIO_BRIDGE_ALLOWED_ORIGINS:-*}"
export TTS_AI_STUDIO_BRIDGE_ALLOWED_ENGINES="${TTS_AI_STUDIO_BRIDGE_ALLOWED_ENGINES:-chatterbox,qwen3,cosyvoice}"

exec python3 ./tts_ai_studio_bridge.py
