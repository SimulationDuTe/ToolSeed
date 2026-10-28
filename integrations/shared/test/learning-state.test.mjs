import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createLearningState, restoreLearningState, reduceLearning, nextLearningHint,
  LEARNING_POLICY} from '../learning-state.mjs';

const ref = {capability_id: 'cap_one', version_id: 'ver_one', invocation_id: 'inv_one',
  content_hash: 'sha256:' + 'a'.repeat(64)};
const step = (state, event) => reduceLearning(state, event).state;
const activity = (id, failed = false) => ({type: 'tool_result', kind: 'activity', id, tool: 'inspect', failed});

test('a return before a failure cannot become progress after that failure', () => {
  const first = step(createLearningState('t'), activity('a'));
  const saved = structuredClone(first);
  const failed = step(first, activity('b', true));
  assert.deepEqual(first, saved);
  assert.equal(nextLearningHint(failed), undefined);
  const progress = step(failed, activity('c'));
  assert.equal(nextLearningHint(progress).reason, 'progress_after_failure');
});

test('proposal, host return and committed receipt remain distinct and monotonic', () => {
  let state = step(step(createLearningState('t'), activity('a', true)), activity('b'));
  const hint = nextLearningHint(state);
  state = step(state, {type: 'hint_receipt', ...hint, status: 'proposed'});
  assert.equal(nextLearningHint(state), undefined);
  assert.equal(state.hints.general.status, 'proposed');
  state = step(state, {type: 'hint_receipt', ...hint, status: 'rejected'});
  assert.equal(nextLearningHint(state).id, hint.id);
  state = step(state, {type: 'hint_receipt', ...hint, status: 'returned'});
  assert.equal(state.hints.general.status, 'returned');
  state = step(state, {type: 'hint_receipt', ...hint, status: 'committed'});
  state = step(state, {type: 'hint_receipt', ...hint, status: 'proposed'});
  assert.equal(state.hints.general.status, 'committed');
});

test('only exact accepted feedback closes a delivery and retries cannot reopen it', () => {
  let state = step(createLearningState('t'), {type: 'tool_result', id: 'run', kind: 'delivery', delivery: ref});
  assert.equal(nextLearningHint(state), undefined);
  state = step(state, {type: 'tool_result', id: 'wrong', kind: 'learning', accepted: true,
    feedback: {...ref, content_hash: 'sha256:' + 'b'.repeat(64)}});
  assert.equal(state.deliveries.length, 1);
  state = step(state, {type: 'tool_result', id: 'accepted', kind: 'learning', accepted: true, feedback: ref});
  state = step(state, {type: 'tool_result', id: 'retry', kind: 'delivery', delivery: ref});
  state = step(state, {type: 'user_message'});
  assert.equal(state.deliveries.length, 0);
  assert.equal(nextLearningHint(state), undefined);
});

test('user follow-up carries pending references, cancellation and unrelated turns clear them', () => {
  let state = step(createLearningState('t'), {type: 'tool_result', id: 'run', kind: 'delivery', delivery: ref});
  assert.equal(step(state, {type: 'turn_started', turn: 'unrelated'}).deliveries.length, 0);
  state = step(state, {type: 'user_message', prompt: 'NEVER_RETAIN_RAW_USER_TEXT'});
  state = step(state, {type: 'turn_started', turn: 'next'});
  assert.equal(nextLearningHint(state).deliveries[0].invocation_id, ref.invocation_id);
  assert.equal(JSON.stringify(state).includes('NEVER_RETAIN'), false);
  state = step(state, {type: 'canceled'});
  assert.equal(nextLearningHint(state), undefined);
  assert.equal(step(state, {type: 'turn_started', turn: 'later', userInitiated: true}).deliveries.length, 0);
});

test('observation limits, duplicated calls and persisted-state validation remain bounded', () => {
  let state = createLearningState('t');
  for (let index = 0; index < 300; index++) state = step(state, activity('call-' + index));
  assert.equal(state.actions, LEARNING_POLICY.actions);
  assert.equal(state.seen.length, LEARNING_POLICY.executions);
  assert.deepEqual(step(state, activity('call-0', true)), state);
  assert.deepEqual(restoreLearningState(state, 't'), state);
  assert.deepEqual(restoreLearningState({v: 1, deliveries: 'bad'}, 't'), createLearningState('t'));
});

test('DSH packaged rules are byte-identical to canonical shared source', () => {
  assert.deepEqual(readFileSync(new URL('../../dsh/lib/learning-state.mjs', import.meta.url)),
    readFileSync(new URL('../learning-state.mjs', import.meta.url)));
});
