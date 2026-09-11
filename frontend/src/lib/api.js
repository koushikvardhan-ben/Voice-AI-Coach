export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
export const WS_BASE = import.meta.env.VITE_WS_BASE || API_BASE.replace(/^http/, "ws");

export async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
      signal: options.signal || AbortSignal.timeout(12000),
    });
  } catch (e) {
    throw new Error(e.name === "TimeoutError" ? "The server took too long to respond. Try again." : "Cannot reach the backend. Start the FastAPI service on port 8000.");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status}). Check your inputs and try again.`);
  }
  return res.status === 204 ? null : res.json();
}
export const fetchToken = () => api("/api/token");
