const MAP = {
  idle: {
    label: "Idle",
    cls: "text-on-surface-variant border-outline-variant/40 bg-surface-container/60",
  },
  dialing: {
    label: "Dialing",
    cls: "text-primary border-primary/40 bg-primary/10",
    pulse: true,
  },
  ringing: {
    label: "Ringing",
    cls: "text-primary border-primary/40 bg-primary/10",
    pulse: true,
  },
  connected: {
    label: "Connected",
    cls: "text-secondary border-secondary/40 bg-secondary/10",
    pulse: true,
  },
  ended: {
    label: "Call ended",
    cls: "text-on-surface-variant border-outline-variant/40 bg-surface-container/60",
  },
  failed: {
    label: "Failed",
    cls: "text-error border-error/40 bg-error/10",
  },
};

export default function StatusBadge({ status }) {
  const s = MAP[status] || MAP.idle;
  return (
    <div
      className={`inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-xs font-semibold font-label-caps tracking-wide ${s.cls}`}
    >
      <span className={`h-2 w-2 rounded-full bg-current ${s.pulse ? "animate-pulse-dot" : ""}`} />
      {s.label}
    </div>
  );
}
