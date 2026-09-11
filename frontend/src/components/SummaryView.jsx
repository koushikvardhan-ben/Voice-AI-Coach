const OUTCOME_LABEL = {
  progressed: "Progressed",
  stalled: "Stalled",
  lost: "Lost",
  unclear: "Unclear",
};

function List({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="summary-list">
      <h4>{title}</h4>
      <ul>
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}

export default function SummaryView({ summary }) {
  if (!summary) return null;
  return (
    <section className="panel summary-panel">
      <div className="coach-head">
        <h2 className="panel-title">Post-call Summary</h2>
        <span className={`chip outcome-${summary.outcome}`}>
          {OUTCOME_LABEL[summary.outcome] || summary.outcome}
        </span>
      </div>
      <List title="Key points" items={summary.key_points} />
      <List title="Objections raised" items={summary.objections} />
      <List title="Commitments made" items={summary.commitments} />
      <List title="Recommended next steps" items={summary.next_steps} />
    </section>
  );
}
