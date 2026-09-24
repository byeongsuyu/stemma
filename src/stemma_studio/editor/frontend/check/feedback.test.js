import test from 'node:test';
import assert from 'node:assert/strict';
import {speak} from './catalog.js';
import {failureKind, failureStatus, refusal, sourceOrigin, dateText, dateDetail, DATE_KINDS} from '../feedback.js';

test('a refused request does not offer to retry the save', () => {
  assert.equal(failureKind(400), 'refused');
  assert.match(failureStatus('refused'), /입력을 확인/);
  assert.ok(!/저장 또는 요청 실패/.test(failureStatus('refused')));
});
test('a moved workspace asks for a reload rather than another save', () => {
  assert.equal(failureKind(409), 'stale');
  assert.match(failureStatus('stale'), /새로고침/);
});
test('a dropped connection or server fault is the case retry exists for', () => {
  for (const status of [undefined, 0, 500, 503]) assert.equal(failureKind(status), 'failed');
  assert.match(failureStatus('failed'), /저장 또는 요청 실패/);
});
test('a guard the desk enforced itself is not a request waiting to be retried', () => {
  const guard = refusal('수정한 한국어 원고를 판본으로 먼저 저장해 주세요.');
  assert.equal(failureKind(guard.status), 'local');
  assert.equal(guard.message, '수정한 한국어 원고를 판본으로 먼저 저장해 주세요.');
  assert.ok(!/저장 또는 요청 실패/.test(failureStatus('local')));
  assert.match(failureStatus('local'), /아직 보내지 않았습니다/);
});
test('provenance never prints a field the source does not have', () => {
  const folder = sourceOrigin({origin: 'folder', relative_path: 'posts/a.md'});
  assert.ok(!folder.includes('undefined'), folder);
  assert.ok(!folder.includes('commit'), folder);
  assert.match(folder, /posts\/a\.md/);
});
test('a Git import still names its commit, and Studio writing names neither', () => {
  assert.match(sourceOrigin({origin: 'archive', relative_path: 'p.md', commit: 'abc123'}), /보관 commit: abc123/);
  assert.equal(sourceOrigin(null), 'Stemma에서 작성한 원고');
  assert.equal(sourceOrigin({origin: 'editor'}), 'Stemma에서 작성한 원고');
  assert.ok(!sourceOrigin({origin: 'archive', relative_path: 'p.md'}).includes('undefined'));
});

test('a document without a usable date says so rather than showing nothing', () => {
  for (const missing of [null, undefined, '']) {
    assert.equal(dateText(missing), '날짜 미상');
    assert.equal(dateDetail(missing, 'created'), '날짜 미상');
  }
});
test('the detail surfaces say which date they are showing', () => {
  assert.equal(dateDetail('2011-09-27', 'source'), '2011-09-27 · 원문 날짜');
  assert.equal(dateDetail('2026-09-19', 'created'), '2026-09-19 · Studio 최초 저장');
});
test('an unrecognised kind falls back rather than printing the raw value', () => {
  assert.equal(dateDetail('2026-09-19', 'edited_at'), '2026-09-19 · 날짜 미상');
  assert.equal(dateDetail('2026-09-19', undefined), '2026-09-19 · 날짜 미상');
});
test('every surface draws its date words from the one map', () => {
  assert.deepEqual(Object.keys(DATE_KINDS).sort(), ['created', 'source', 'unknown']);
});
