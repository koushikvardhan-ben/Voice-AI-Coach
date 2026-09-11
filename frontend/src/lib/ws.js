import { WS_BASE } from "./api";

// Open the browser-facing WebSocket for a call. Events arrive as JSON with a
// `type` discriminator (status | transcript | coach | summary | notice).
export function openBrowserSocket(callId, onEvent, onClose) {
  const ws = new WebSocket(`${WS_BASE}/ws/${callId}`);
  ws.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      /* ignore malformed frame */
    }
  };
  ws.onclose = () => onClose && onClose();
  ws.onerror = () => {};
  return ws;
}
