# HandAISpoke / AI Studio TTS Bridge

The AI Studio bridge is an optional local sidecar for requesting short speech patches from the local TTS stack.

It is intended for workflows like:

```text
HandAISpoke / Google AI Studio preview
  → local AI Studio bridge on 127.0.0.1:7871
  → TTS Unified WebUI on 127.0.0.1:7870
  → /home/user/tts-lab/tts-lab.sh synth chatterbox|qwen3|cosyvoice
  → WAV/base64 patch returned to the caller
```

## Important wording

Gemini / Google AI Studio is **not** the voice-cloning engine in this architecture.

Use wording like:

```text
Local TTS bridge active: cloned/custom voice generation is handled by your configured local TTS engine, not Gemini.
```

Do not describe Gemini as replicating the uploaded voice profile. Gemini may help choose or reason about repair text, but local engines such as Chatterbox, Qwen3, and CosyVoice perform the custom voice generation.

## Security boundary

The bridge is deliberately narrower than the full Web UI.

Allowed:

```text
text + selected engine + reference audio → short generated WAV patch
```

Not allowed:

```text
arbitrary shell commands
arbitrary file access
deleting outputs
managing profiles
restarting services
launching desktop apps
exposing the full browser control panel
```

Hard requirements:

```text
- The bridge is disabled unless explicitly launched.
- The bridge binds to 127.0.0.1 by default.
- Every API request requires X-HandAISpoke-Bridge-Token.
- The token comes from TTS_AI_STUDIO_BRIDGE_TOKEN.
- Do not expose the full Web UI through Cloudflare.
- Do not log full reference audio or long full text.
```

## Files

```text
webui/tts_ai_studio_bridge.py
webui/run-ai-studio-bridge.sh
webui/.env.ai-studio-bridge.example
tests/test_ai_studio_bridge_request.py
docs/api-contract.md
docs/cloudflare-testing.md
docs/AI_STUDIO_HELPER.ts
```

## Launch locally

Start the normal Web UI first:

```bash
/home/user/tts-lab/start-tts-webui.sh
```

Then start the bridge in a separate terminal/session with a token you generated locally:

```bash
export TTS_AI_STUDIO_BRIDGE_TOKEN='replace-with-a-long-random-local-token'
/home/user/tts-lab/start-ai-studio-bridge.sh
```

Default bridge URL:

```text
http://127.0.0.1:7871
```

Default Web UI URL the bridge calls internally:

```text
http://127.0.0.1:7870
```

## Configuration

See `.env.example` and `webui/.env.ai-studio-bridge.example`.

Supported environment variables:

```bash
TTS_AI_STUDIO_BRIDGE_TOKEN=
TTS_AI_STUDIO_BRIDGE_HOST=127.0.0.1
TTS_AI_STUDIO_BRIDGE_PORT=7871
TTS_WEBUI_BASE=http://127.0.0.1:7870
TTS_AI_STUDIO_BRIDGE_ALLOWED_ORIGINS=*
TTS_AI_STUDIO_BRIDGE_ALLOWED_ENGINES=chatterbox,qwen3,cosyvoice
TTS_AI_STUDIO_BRIDGE_MAX_TEXT_CHARS=1200
TTS_AI_STUDIO_BRIDGE_MAX_REF_BYTES=20971520
TTS_AI_STUDIO_BRIDGE_TIMEOUT_SECONDS=90
```

Do not commit a real token.

## Logging

Bridge log path:

```text
/home/user/tts-lab/logs/ui-diagnostics/ai-studio-bridge.log
```

Each request logs:

```text
request_id
origin
engine
text length
reference audio byte size
reference SHA-256 prefix
job_id
status
elapsed time
output size
error stage
```

It does not log full base64 audio or full script text.

## Local smoke test

With the Web UI and bridge running:

```bash
python3 tests/test_ai_studio_bridge_request.py \
  --token "$TTS_AI_STUDIO_BRIDGE_TOKEN" \
  --ref /home/user/tts-lab/references/voice_ref.wav \
  --engine chatterbox \
  --save /tmp/bridge-test-output.wav
```

The saved WAV should be playable if the local engine stack is working.
