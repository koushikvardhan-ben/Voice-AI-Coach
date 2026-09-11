import test from 'node:test';
import assert from 'node:assert/strict';
import { mergeCallStatus, upsertTurn, mergeCoach, mergeCoachStatus } from '../src/lib/callEvents.js';

test('later confirmed segments update the same transcript row without losing words', () => {
  const first = { id: 'agent-1', seq: 1, speaker: 'agent', text: 'What is your' };
  const customer = { id: 'customer-1', seq: 2, speaker: 'customer', text: 'Eighty five lakh.' };
  const turns = upsertTurn([first, customer], { ...first, text: 'What is your budget?' });
  assert.equal(turns.length, 2);
  assert.equal(turns[0].text, 'What is your budget?');
  assert.equal(turns[1].speaker, 'customer');
  assert.equal(first.text, 'What is your');
});

test('late ringing callback does not regress an answered call', () => {
  assert.equal(mergeCallStatus('connected', 'ringing'), 'connected');
  assert.equal(mergeCallStatus('connected', 'dialing'), 'connected');
  assert.equal(mergeCallStatus('ringing', 'connected'), 'connected');
});

test('late answer cannot resurrect an ended call', () => {
  assert.equal(mergeCallStatus('ended', 'connected'), 'ended');
  assert.equal(mergeCallStatus('failed', 'ringing'), 'failed');
  assert.equal(mergeCallStatus('connected', 'nonsense'), 'connected');
});

test('an old queued final cannot overwrite a newer reconnect snapshot', () => {
  const newest = { id: 'same-turn', seq: 1, revision: 3, text: 'Complete confirmed sentence.' };
  const restored = upsertTurn([newest], { ...newest, revision: 1, text: 'Complete' });
  assert.deepEqual(restored, [newest]);
});

test('replayed older suggestions cannot replace a newer conversation update', () => {
  const current = { based_on_revision: 8, updated_at: 100, next_move: 'Clarify the quoted price unit.' };
  const old = { based_on_revision: 3, updated_at: 90, next_move: 'Ask their asking price.' };
  assert.equal(mergeCoach(current, old), current);
  const next = { ...current, based_on_revision: 9, updated_at: 104, next_move: 'Address the pricing objection.' };
  assert.equal(mergeCoach(current, next), next);
});

test('old status events cannot hide a current generation error or rate limit', () => {
  const current = { ts: 105, state: 'rate_limited' };
  assert.equal(mergeCoachStatus(current, { ts: 100, state: 'current' }), current);
  const restored = { ts: 120, state: 'updating' };
  assert.equal(mergeCoachStatus(current, restored), restored);
});
