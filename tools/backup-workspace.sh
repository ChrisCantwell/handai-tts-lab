#!/usr/bin/env bash
# HandAI TTS Lab workspace backup tool.
#
# Backs up runtime data and/or models from a TTS Lab installation so it can be
# restored to a fresh install later.
#
# Usage:
#   backup-workspace.sh [--workspace] [--models] [--all] [--source-dir PATH] [--output-dir PATH]
#
# Defaults:
#   Source:  $TTS_LAB or /home/user/tts-lab
#   Output:  $TTS_BACKUP_DIR or ~/handai-tts-lab/backups
#
# Examples:
#   backup-workspace.sh --all
#   backup-workspace.sh --workspace --source-dir /home/user/tts-lab
#   backup-workspace.sh --models --output-dir /mnt/external/handai-tts-lab-backups

set -Eeuo pipefail

VERSION="0.1.0"
DEFAULT_SOURCE="${TTS_LAB:-/home/user/tts-lab}"
DEFAULT_OUTPUT="${TTS_BACKUP_DIR:-${HOME}/handai-tts-lab/backups}"

SOURCE_DIR="${DEFAULT_SOURCE}"
OUTPUT_DIR="${DEFAULT_OUTPUT}"
BACKUP_WORKSPACE=0
BACKUP_MODELS=0
DRY_RUN=0

usage() {
  cat <<EOF
HandAI TTS Lab backup tool v${VERSION}

Usage: $(basename "$0") [options]

Options:
  -w, --workspace       Backup user workspace (output, projects, references, config, job history).
  -m, --models          Backup downloaded models and caches.
  -a, --all             Backup both workspace and models.
  -s, --source-dir DIR  Source TTS Lab directory. Default: ${DEFAULT_SOURCE}
  -o, --output-dir DIR  Directory for backup archives. Default: ${DEFAULT_OUTPUT}
  -n, --dry-run         Print what would be backed up without writing archives.
  -h, --help            Show this help.

Environment:
  TTS_LAB               Default source directory.
  TTS_BACKUP_DIR        Default output directory.

Notes:
  - Workspace backups exclude tmp/, logs/, and the webui Python files.
  - Model backups include .cache/huggingface/ and .cache/torch/.
  - Each run creates a timestamped archive and a manifest JSON file.
EOF
}

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '[%s] WARN %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
fail() { printf '[%s] FAIL %s\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -w|--workspace) BACKUP_WORKSPACE=1; shift ;;
    -m|--models) BACKUP_MODELS=1; shift ;;
    -a|--all) BACKUP_WORKSPACE=1; BACKUP_MODELS=1; shift ;;
    -s|--source-dir) SOURCE_DIR="$2"; shift 2 ;;
    -o|--output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    -n|--dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

if [[ "$BACKUP_WORKSPACE" -eq 0 && "$BACKUP_MODELS" -eq 0 ]]; then
  # Default to workspace-only if no mode specified.
  BACKUP_WORKSPACE=1
fi

SOURCE_DIR="$(cd "$SOURCE_DIR" 2>/dev/null && pwd)" || fail "Source directory does not exist: $SOURCE_DIR"
OUTPUT_DIR_ABS="$OUTPUT_DIR"
if [[ "$DRY_RUN" -eq 0 ]]; then
  mkdir -p "$OUTPUT_DIR_ABS"
  OUTPUT_DIR_ABS="$(cd "$OUTPUT_DIR_ABS" && pwd)"
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${OUTPUT_DIR_ABS}/${TIMESTAMP}"
MANIFEST="${RUN_DIR}/manifest.json"

calculate_size() {
  local path="$1"
  if [[ -d "$path" ]]; then
    du -sb "$path" 2>/dev/null | awk '{print $1}'
  elif [[ -f "$path" ]]; then
    stat -c%s "$path" 2>/dev/null || stat -f%z "$path" 2>/dev/null
  else
    echo 0
  fi
}

human_size() {
  local bytes="$1"
  numfmt --to=iec-i --suffix=B "$bytes" 2>/dev/null || echo "${bytes} bytes"
}

# Collect workspace paths.
workspace_paths=()
if [[ "$BACKUP_WORKSPACE" -eq 1 ]]; then
  for rel in output projects references config; do
    if [[ -e "${SOURCE_DIR}/${rel}" ]]; then
      workspace_paths+=("$rel")
    else
      warn "Source path not found, skipping: ${SOURCE_DIR}/${rel}"
    fi
  done
  if [[ -d "${SOURCE_DIR}/scripts" ]]; then
    workspace_paths+=("scripts")
  fi
  if [[ -d "${SOURCE_DIR}/engines/resemble-enhance" ]]; then
    for f in resemble-enhance-webui resemble_enhance_webui_wrapper.py; do
      if [[ -e "${SOURCE_DIR}/engines/resemble-enhance/${f}" ]]; then
        workspace_paths+=("engines/resemble-enhance/${f}")
      fi
    done
  fi
fi

# Collect model paths.
model_paths=()
if [[ "$BACKUP_MODELS" -eq 1 ]]; then
  for rel in .cache/huggingface .cache/torch; do
    if [[ -e "${SOURCE_DIR}/${rel}" ]]; then
      model_paths+=("$rel")
    else
      warn "Model path not found, skipping: ${SOURCE_DIR}/${rel}"
    fi
  done
  for rel in engines/whisperx engines/crisperwhisper; do
    if [[ -d "${SOURCE_DIR}/${rel}" ]]; then
      model_paths+=("$rel")
    fi
  done
fi

if [[ ${#workspace_paths[@]} -eq 0 && ${#model_paths[@]} -eq 0 ]]; then
  fail "Nothing to back up. Check source directory: $SOURCE_DIR"
fi

# Print summary.
log "Source: $SOURCE_DIR"
log "Output: $OUTPUT_DIR_ABS"
log "Modes: workspace=${BACKUP_WORKSPACE} models=${BACKUP_MODELS}"
total_bytes=0
for p in "${workspace_paths[@]}"; do
  size=$(calculate_size "${SOURCE_DIR}/${p}")
  total_bytes=$((total_bytes + size))
  log "  workspace: ${p} ($(human_size "$size"))"
done
for p in "${model_paths[@]}"; do
  size=$(calculate_size "${SOURCE_DIR}/${p}")
  total_bytes=$((total_bytes + size))
  log "  models: ${p} ($(human_size "$size"))"
done
log "Estimated total: $(human_size "$total_bytes")"

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "Dry run complete. No archives written."
  exit 0
fi

mkdir -p "$RUN_DIR"

# Write initial manifest.
cat > "$MANIFEST" <<EOF
{
  "version": "${VERSION}",
  "created_at": "$(date -Iseconds)",
  "source_dir": "${SOURCE_DIR}",
  "backup_dir": "${RUN_DIR}",
  "modes": {
    "workspace": ${BACKUP_WORKSPACE},
    "models": ${BACKUP_MODELS}
  },
  "archives": [],
  "items": [],
  "verification": {},
  "total_size_bytes": 0
}
EOF

# Build tar excludes.
EXCLUDE_FILE="${RUN_DIR}/excludes.txt"
cat > "$EXCLUDE_FILE" <<'EOF'
__pycache__
*.pyc
*.pyo
*.log
tmp/
*.tmp
.DS_Store
EOF

archive_count=0
backup_item() {
  local kind="$1"
  local rel_path="$2"
  local src="${SOURCE_DIR}/${rel_path}"
  local safe_name
  safe_name="$(echo "$rel_path" | tr '/ ' '__')"
  local archive="${RUN_DIR}/${kind}-${safe_name}-${TIMESTAMP}.tar"

  log "Archiving ${kind}: ${rel_path} -> ${archive}.gz"
  tar -cf "$archive" -C "$SOURCE_DIR" --exclude-from="$EXCLUDE_FILE" "$rel_path"
  # Use fast compression. Model caches are mostly pre-compressed; -1 gives a
  # reasonable size reduction without the multi-minute CPU cost of -9.
  gzip -1 "$archive"
  archive_count=$((archive_count + 1))

  local size
  size=$(calculate_size "${archive}.gz")
  python3 - "$MANIFEST" "$kind" "$rel_path" "${archive}.gz" "$size" <<'PY'
import json, sys
manifest_path, kind, rel_path, archive_path, size = sys.argv[1:]
with open(manifest_path) as f:
    data = json.load(f)
data["archives"].append({
    "kind": kind,
    "rel_path": rel_path,
    "archive": archive_path,
    "size_bytes": int(size)
})
data["items"].append({
    "kind": kind,
    "rel_path": rel_path,
    "size_bytes": int(size)
})
with open(manifest_path, "w") as f:
    json.dump(data, f, indent=2)
PY
}

for p in "${workspace_paths[@]}"; do
  backup_item "workspace" "$p"
done

for p in "${model_paths[@]}"; do
  backup_item "models" "$p"
done

# Verify each archive can be listed.
log "Verifying archives..."
verified=0
failed=0
while IFS= read -r archive; do
  if tar -tzf "$archive" >/dev/null 2>&1; then
    verified=$((verified + 1))
  else
    warn "Archive verification failed: $archive"
    failed=$((failed + 1))
  fi
done < <(find "$RUN_DIR" -maxdepth 1 -name '*.tar.gz' -type f)

if [[ "$failed" -gt 0 ]]; then
  fail "$failed archive(s) failed verification."
fi

final_bytes=$(calculate_size "$RUN_DIR")
python3 - "$MANIFEST" "$verified" "$failed" "$final_bytes" <<'PY'
import json, sys
path, verified, failed, final_bytes = sys.argv[1:]
with open(path) as f:
    data = json.load(f)
data["verification"] = {
    "archives_verified": int(verified),
    "archives_failed": int(failed)
}
data["total_size_bytes"] = int(final_bytes)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
PY

log "Backup complete."
log "Location: ${RUN_DIR}"
log "Archives: ${archive_count} ($(human_size "$final_bytes"))"
log "Manifest: ${MANIFEST}"
log "To restore, unpack each .tar.gz archive into the new TTS_LAB directory."
