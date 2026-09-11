import { useEffect, useState } from "react";

const STAGES = [
  { key: "opening", label: "Opening" },
  { key: "discovery", label: "Discovery" },
  { key: "objection_handling", label: "Objections" },
  { key: "closing", label: "Closing" },
];

const SENTIMENT_LABEL = {
  cold: "Cold",
  neutral: "Neutral",
  warm: "Warm",
  hot: "Hot",
  frustrated: "Frustrated",
};

function tempColor(t) {
  if (t >= 70) return "#e0483d"; // hot
  if (t >= 45) return "#e08a1e"; // warm
  return "#2f80c2"; // cool
}

function useAgo(ts) {
  const [, force] = useState(0);
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  if (!ts) return null;
  const secs = Math.max(0, Math.round(Date.now() / 1000 - ts));
  return secs < 2 ? "just now" : `${secs}s ago`;
}

export default function CoachPanel({ coach }) {
  const ago = useAgo(coach?.updated_at);

  if (!coach) {
    return (
      <section className="panel coach-panel">
        <h2 className="panel-title">AI Sales Coach</h2>
        <p className="muted">
          Coaching appears here once the customer starts talking — the current
          stage, how warm they are, and your best next move.
        </p>
      </section>
    );
  }

  const temp = coach.temperature ?? 50;

  return (
    <section className="panel coach-panel">
      <div className="coach-head">
        <h2 className="panel-title">AI Sales Coach</h2>
        {ago ? <span className="coach-ago">updated {ago}</span> : null}
      </div>

      <div className="stage-stepper">
        {STAGES.map((s) => (
          <div
            key={s.key}
            className={`stage-step ${coach.stage === s.key ? "active" : ""}`}
          >
            {s.label}
          </div>
        ))}
      </div>

      <div className="coach-meta">
        <span className="chip">
          {coach.customer_role === "unknown" ? "Role: unknown" : `Role: ${coach.customer_role}`}
        </span>
        <span className="chip">
          {SENTIMENT_LABEL[coach.sentiment] || coach.sentiment}
        </span>
      </div>

      <div className="temp-block">
        <div className="temp-label">
          <span>Temperature</span>
          <span>{temp}/100</span>
        </div>
        <div className="temp-track">
          <div
            className="temp-fill"
            style={{ width: `${temp}%`, background: tempColor(temp) }}
          />
        </div>
      </div>

      <div className="next-move">
        <span className="next-move-label">Next best move</span>
        <p className="next-move-text">{coach.next_move || "—"}</p>
        {coach.rationale ? <p className="rationale">{coach.rationale}</p> : null}
      </div>
    </section>
  );
}
