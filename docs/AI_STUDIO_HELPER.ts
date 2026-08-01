// Minimal helper for calling the local HandAISpoke / AI Studio TTS bridge.
// The bridge URL may be a Cloudflare quick-tunnel URL during testing.

export type LocalTtsBridgeRequest = {
  request_id?: string;
  engine?: 'chatterbox' | 'qwen3' | 'cosyvoice';
  text: string;
  reference_audio_base64: string;
  reference_mime_type?: string;
  reference_text?: string;
  return_format?: 'json_base64' | 'raw_wav';
  mode?: 'sync' | 'async';
  timeout_seconds?: number;
};

export async function callLocalTtsBridge(
  bridgeBaseUrl: string,
  token: string,
  payload: LocalTtsBridgeRequest,
) {
  const response = await fetch(`${bridgeBaseUrl.replace(/\/$/, '')}/api/ai-studio-bridge/clone-tts`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-HandAISpoke-Bridge-Token': token,
    },
    body: JSON.stringify({
      engine: 'chatterbox',
      return_format: 'json_base64',
      mode: 'sync',
      timeout_seconds: 90,
      ...payload,
    }),
  });

  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data?.error || `Local TTS bridge failed with HTTP ${response.status}`);
  }
  return data;
}

export function bridgeMessageForUi() {
  return 'Local TTS bridge active: cloned/custom voice generation is handled by your configured local TTS engine, not Gemini.';
}
