export const voiceDeviceOptions = {
  codecPreferences: ["opus", "pcmu"],
  logLevel: "error",
  // Preserve the current call while signaling reconnects to the same edge.
  maxCallSignalingTimeoutMs: 30000,
  enableImprovedSignalingErrorPrecision: true,
};

export const voiceError = e => `${e.message || "Calling connection error"}${e.code ? ` (Twilio ${e.code})` : ""}`;

export function watchCallConnection(call, { report, notice, error, finish }) {
  call.on("reconnecting", e => {
    report("reconnecting", e);
    notice(`Call connection interrupted; reconnecting…${e.code ? ` (Twilio ${e.code})` : ""}`);
  });
  call.on("reconnected", () => { report("reconnected"); notice("Call connection restored."); });
  call.on("warning", name => { report("warning", { code: name }); });
  call.on("disconnect", () => { report("disconnect"); finish(); });
  call.on("cancel", () => { report("cancel"); finish(); });
  call.on("error", e => {
    const closed = call.status() === "closed";
    report("error", e, closed);
    error(voiceError(e));
    // A recoverable media/signaling error must not end the dashboard session.
    if (closed) finish(true);
  });
}
