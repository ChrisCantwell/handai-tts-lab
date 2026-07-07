# AI Studio Bridge API Contract

Base URL, local default:

```text
http://127.0.0.1:7871
```

All endpoints require:

```text
X-HandAISpoke-Bridge-Token: <token>
```

The token is configured with:

```text
TTS_AI_STUDIO_BRIDGE_TOKEN
```

## Status

```http
GET /api/ai-studio-bridge/status
```

Success response:

```json
{
  "ok": true,
  "bridge": "handaispoke-tts-ai-studio-bridge",
  "bridge_version": "0.87",
  "webui_base": "http://127.0.0.1:7870",
  "webui_version": "0.87",
  "allowed_engines": ["chatterbox", "cosyvoice", "qwen3"],
  "max_text_chars": 1200,
  "max_reference_bytes": 20971520,
  "log_path": "/home/user/tts-lab/logs/ui-diagnostics/ai-studio-bridge.log",
  "message": "Local TTS bridge active: cloned/custom voice generation is handled by your configured local TTS engine, not Gemini."
}
```

## Clone TTS / vocal patch

```http
POST /api/ai-studio-bridge/clone-tts
Content-Type: application/json
```

Request:

```json
{
  "request_id": "handaispoke-20260707-001",
  "engine": "chatterbox",
  "text": "Replacement line to synthesize.",
  "reference_audio_base64": "UklGRi...",
  "reference_mime_type": "audio/wav",
  "reference_text": "Optional transcript of the reference audio.",
  "return_format": "json_base64",
  "mode": "sync",
  "timeout_seconds": 90
}
```

Notes:

- `engine` defaults to `chatterbox`.
- Allowed engines default to `chatterbox`, `qwen3`, and `cosyvoice`.
- F5 is not allowed by default.
- `return_format` can be `json_base64` or `raw_wav` / `wav`.
- `mode` can be `sync` or `async`.
- `reference_audio_base64` may be raw base64 or a data URL.

Sync success response:

```json
{
  "ok": true,
  "request_id": "handaispoke-20260707-001",
  "job_id": "...",
  "engine": "chatterbox",
  "mime_type": "audio/wav",
  "audio_base64": "UklGRi...",
  "duration_seconds": 3.42,
  "output_bytes": 123456,
  "elapsed_seconds": 8.51,
  "job": {
    "id": "...",
    "status": "done",
    "engine": "chatterbox",
    "output_path": "/home/user/tts-lab/output/ai_studio_bridge/...wav"
  }
}
```

Async success response:

```json
{
  "ok": true,
  "request_id": "handaispoke-20260707-001",
  "job_id": "...",
  "job": {
    "id": "...",
    "status": "queued"
  }
}
```

## Job status

```http
GET /api/ai-studio-bridge/jobs/<job_id>
```

Returns a minimized job payload from the Web UI. It intentionally omits full logs and shell command arrays.

## Error shape

```json
{
  "ok": false,
  "request_id": "handaispoke-20260707-001",
  "error": "text is required"
}
```
