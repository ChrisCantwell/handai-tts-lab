# Cloudflare Quick Tunnel Testing for the AI Studio Bridge

For quick Google AI Studio testing, tunnel only the bridge port:

```bash
cloudflared tunnel --url http://127.0.0.1:7871
```

Use the resulting `trycloudflare.com` URL as the bridge base URL in AI Studio or HandAISpoke.

Do **not** tunnel the full Web UI port:

```text
http://127.0.0.1:7870
```

The full Web UI can launch local processes, access workspace files, manage jobs, and open desktop applications. The bridge intentionally exposes only the narrow token-protected speech-patch API.

## Recommended quick-test sequence

1. Start the normal Web UI locally.
2. Start the bridge locally with `TTS_AI_STUDIO_BRIDGE_TOKEN` set.
3. Confirm local status:

```bash
curl -H "X-HandAISpoke-Bridge-Token: $TTS_AI_STUDIO_BRIDGE_TOKEN" \
  http://127.0.0.1:7871/api/ai-studio-bridge/status
```

4. Start the quick tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:7871
```

5. Point the AI Studio helper at the public quick-tunnel URL.
6. Keep the token private.

## Permanent tunnel

A permanent tunnel can come later. Prefer Cloudflare Access plus the bridge token for anything longer-lived than a quick test.
