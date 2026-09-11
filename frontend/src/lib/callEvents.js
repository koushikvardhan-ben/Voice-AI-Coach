const order = { idle: 0, dialing: 1, ringing: 2, connected: 3, ended: 4, failed: 4 };

export function mergeCallStatus(current, incoming) {
  if (!(incoming in order)) return current;
  return order[incoming] < order[current] ? current : incoming;
}

// Deepgram can finalize multiple segments in one utterance. Later versions have
// the same stable ID, so replace the row instead of silently dropping the words.
export function upsertTurn(turns, turn) {
  const index = turns.findIndex(item => item.id === turn.id);
  if (index < 0) return [...turns, turn].sort((a, b) => a.seq - b.seq);
  if ((turn.revision || 0) < (turns[index].revision || 0)) return turns;
  return turns.map((item, i) => i === index ? turn : item);
}

export function mergeCoach(current, incoming) {
  if (!current) return incoming;
  if ((incoming.based_on_revision || 0) < (current.based_on_revision || 0)) return current;
  return incoming.updated_at < current.updated_at ? current : incoming;
}

export function mergeCoachStatus(current, incoming) {
  if (!current) return incoming;
  return (incoming.ts || 0) < (current.ts || 0) ? current : incoming;
}
