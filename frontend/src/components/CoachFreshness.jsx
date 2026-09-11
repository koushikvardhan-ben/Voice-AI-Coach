import { useEffect, useState } from "react";
import { Activity, LoaderCircle } from "lucide-react";

export default function CoachFreshness({ coach, status, active, isDemo }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  const pending = active && ["queued", "updating"].includes(status?.state);
  const retry = Math.max(0, Math.ceil((status?.retry_at || 0) - now / 1000));
  let message = coach ? "Suggestion is up to date" : "Listening for conversation details";
  if (isDemo) message = "Scripted practice suggestion";
  else if (!active) message = coach ? "Last suggestion from this call" : "Coach ready for your next call";
  else if (status?.state === "rate_limited") message = retry ? `Provider rate limit · retry in ${retry}s` : "Provider rate limit · waiting for an update";
  else if (status?.state === "error") message = status.message;
  else if (pending) message = status.state === "updating" ? "Preparing your next move…" : "New details received · update queued";
  const age = Math.max(0, Math.floor((now / 1000) - (coach?.updated_at || now / 1000)));
  return <div className="coach-context" data-state={status?.state}>
    <div role="status">{pending ? <LoaderCircle size={15} className="spin" /> : <Activity size={15} />}{message}</div>
    <p>{coach ? `${active ? `Updated ${age}s ago` : `Updated ${new Date(coach.updated_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`} · ${coach.customer_role === "seller" ? "Vendor" : coach.customer_role === "buyer" ? "Buyer" : "Property"} conversation` : "Budget, motivation, objections, and readiness for the next step."}</p>
  </div>;
}
