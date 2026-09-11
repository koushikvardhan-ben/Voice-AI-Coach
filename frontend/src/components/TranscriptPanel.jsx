import { useEffect, useRef } from "react";

const SPEAKER_LABEL = { agent: "Agent", customer: "Customer" };

export default function TranscriptPanel({ turns, interim }) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, interim]);

  const interimRows = Object.entries(interim).filter(([, text]) => text);
  const empty = turns.length === 0 && interimRows.length === 0;

  return (
    <section className="panel transcript-panel">
      <h2 className="panel-title">Live Transcript</h2>
      <div className="transcript-scroll">
        {empty ? (
          <p className="muted">The conversation will appear here, speaker by speaker.</p>
        ) : null}

        {turns.map((t) => (
          <div key={t.id} className={`turn turn-${t.speaker}`}>
            <span className="turn-speaker">{SPEAKER_LABEL[t.speaker] || t.speaker}</span>
            <div className="turn-bubble">{t.text}</div>
          </div>
        ))}

        {interimRows.map(([speaker, text]) => (
          <div key={`interim-${speaker}`} className={`turn turn-${speaker}`}>
            <span className="turn-speaker">{SPEAKER_LABEL[speaker] || speaker}</span>
            <div className="turn-bubble interim">{text}</div>
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </section>
  );
}
