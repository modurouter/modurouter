const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const ts = require('typescript');
function load(file, deps = {}) { const exports = {}; runInNewContext(ts.transpileModule(readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports, require: name => deps[name] }); return exports; }
const { advancePractice, emptyPractice, practiceVoiceIndex, readPractice } = load('src/lib/learning-journeys.ts');
const topics = load('src/lib/learning-topics.ts');
const { resolveLearningVoice } = load('src/lib/learning-voice.ts', { './learning-topics': topics });
test('wrong answers show a hint, and only the final correct step completes a practice once', () => {
 let p = advancePractice('child', emptyPractice(), 0);
 assert.equal(p.step, 0); assert.equal(p.hint, true); assert.equal(p.completions, 0);
 p = advancePractice('child', p, 1); p = advancePractice('child', p, 0);
 assert.equal(p.complete, false);
 p = advancePractice('child', p, 0); assert.equal(p.complete, true); assert.equal(p.completions, 1);
 assert.equal(advancePractice('child', p, 0).completions, 1);
});
test('voice choices follow the active step, including Korean numbers and ambiguous input', () => {
 assert.equal(practiceVoiceIndex('senior', emptyPractice(), '포장할게요'), 1);
 assert.equal(practiceVoiceIndex('senior', emptyPractice(), '포장 말고'), null);
 assert.equal(practiceVoiceIndex('senior', emptyPractice(), '매장 아니면 포장'), null);
 assert.equal(practiceVoiceIndex('student', { ...emptyPractice(), step: 1 }, '삼이에요'), 0);
 assert.equal(practiceVoiceIndex('child', emptyPractice(), '두 번째 거'), 1);
});
test('each mode resolves spoken order against its own visible activities', () => {
 const view = { open: true, topicId: null };
 for (const mode of ['senior', 'child', 'student']) {
  const first = topics.getLearningTopics(mode)[0];
  assert.equal(resolveLearningVoice('첫 번째 거', view, mode).type, 'practice');
  assert.equal(resolveLearningVoice('두 번째 거', view, mode).topicId, first.id);
 }
 assert.equal(resolveLearningVoice('동화 만들고 싶어', view, 'child').topicId, 'story');
 assert.equal(resolveLearningVoice('키오스크 연습', view, 'student'), null);
 assert.equal(resolveLearningVoice('학습 스튜디오 열어줘', { open: false, topicId: null }, 'student').type, 'open');
});
test('saved progress resumes a valid step and ignores corrupt records', () => {
 const p = advancePractice('senior', emptyPractice(), 1);
 assert.equal(readPractice(JSON.parse(JSON.stringify(p)), 'senior').step, 1);
 assert.equal(readPractice({ step: 999, answers: [] }, 'senior').step, 0);
 assert.equal(readPractice(null, 'child').complete, false);
});
