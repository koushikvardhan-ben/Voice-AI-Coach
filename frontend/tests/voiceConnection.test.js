import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { voiceDeviceOptions, watchCallConnection } from '../src/lib/voiceConnection.js';

function connection() {
  const call = new EventEmitter();
  let state = 'open';
  call.status = () => state;
  const events = [], endings = [], errors = [];
  watchCallConnection(call, {
    report: (...args) => events.push(args), notice: () => {},
    error: e => errors.push(e), finish: failed => endings.push(failed),
  });
  return { call, events, endings, errors, close: () => { state = 'closed'; } };
}

test('SDK signaling loss gets a reconnection window', () => {
  assert.equal(voiceDeviceOptions.maxCallSignalingTimeoutMs, 30000);
});

test('temporary signaling errors and recovery do not finalize a live call', () => {
  const c = connection();
  c.call.emit('reconnecting', { code: 53001 });
  c.call.emit('error', { code: 53001, message: 'Signaling interrupted' });
  c.call.emit('reconnected');
  assert.equal(c.endings.length, 0);
  assert.deepEqual(c.events.map(e => e[0]), ['reconnecting', 'error', 'reconnected']);
  assert.match(c.errors[0], /53001/);
});

test('a closed call error is reported as terminal', () => {
  const c = connection(); c.close();
  c.call.emit('error', { code: 31003, message: 'Connection failed' });
  assert.deepEqual(c.endings, [true]);
  assert.equal(c.events[0][2], true);
});

test('actual disconnect and cancellation are terminal', () => {
  for (const event of ['disconnect', 'cancel']) {
    const c = connection(); c.close(); c.call.emit(event);
    assert.equal(c.endings.length, 1);
    assert.equal(c.events[0][0], event);
  }
});
