import test from 'node:test';
import assert from 'node:assert/strict';
import { canMutate, initialState, reduce } from './state.mjs';

test('single writer controls mutation', () => {
  const state = reduce(initialState, { kind: 'session.created', writerId: 'human-a', epoch: 1 });
  assert.equal(canMutate(state, 'human-a'), true);
  assert.equal(canMutate(state, 'agent-b'), false);
});

test('tab identity is stable and termination is visible', () => {
  let state = reduce(initialState, { kind: 'tab.opened', tab: { id: 'page-2', title: 'Evidence', lifecycle: 'open', generation: 1 } });
  state = reduce(state, { kind: 'tab.opened', tab: { id: 'page-2', title: 'Duplicate', lifecycle: 'open', generation: 1 } });
  state = reduce(state, { kind: 'page.terminated', id: 'page-2' });
  assert.equal(state.tabs.length, 2);
  assert.equal(state.tabs[1].lifecycle, 'terminated');
});

test('blocked capability remains explicit', () => {
  const state = reduce(initialState, { kind: 'capability.report', backend: 'servo-gtk', status: 'unsupported' });
  assert.deepEqual(state.capability, { backend: 'servo-gtk', status: 'unsupported' });
});
