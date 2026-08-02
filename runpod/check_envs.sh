#!/usr/bin/env bash
set -euo pipefail
CONDA_ROOT="${CONDA_ROOT:-/workspace/miniconda3}"
verify_env() {
  local env_name="$1"
  local py_bin="${CONDA_ROOT}/envs/${env_name}/bin/python"
  [[ -x "$py_bin" ]] || return 1
  "$py_bin" -c "import encodings, sys; print('ok', sys.prefix)" >/dev/null 2>&1
}
base_conda_healthy() {
  local py_bin="${CONDA_ROOT}/bin/python"
  [[ -x "$py_bin" ]] || return 1
  "$py_bin" -c "import encodings; print('base ok')" >/dev/null 2>&1
}
echo "base conda: $(base_conda_healthy && echo healthy || echo broken)"
for env in tts-chatterbox tts-qwen3 tts-cosyvoice tts-whisper tts-f5 tts-whisperx tts-crisperwhisper; do
  echo "$env: $(verify_env "$env" && echo healthy || echo broken)"
done
