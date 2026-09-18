const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const ts = require('typescript');

function store(localStorage) {
  const exports = {};
  const source = ts.transpileModule(readFileSync('src/lib/chat-store.ts', 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  runInNewContext(source, { exports, require, localStorage });
  return exports.useChatStore;
}

for (const mode of ['senior', 'child', 'student']) {
  test(`${mode} survives a new store and conversation reset`, () => {
    const values = new Map();
    const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
    const first = store(storage);
    first.getState().setMode(mode);
    const reloaded = store(storage);
    assert.equal(reloaded.getState().mode, 'student'); // Match the server before mounting.
    reloaded.getState().restoreMode();
    assert.equal(reloaded.getState().mode, mode);
    reloaded.getState().setConversationId('conversation');
    reloaded.getState().setMessages([{ id: 'message', role: 'user', content: 'hello' }]);
    reloaded.getState().setConversationId(null);
    reloaded.getState().setMessages([]);
    assert.equal(reloaded.getState().mode, mode);
    assert.equal(values.size, 1);
  });
}

test('invalid saved modes retain the default and blocked storage allows switching', () => {
  const invalid = store({ getItem: () => 'unknown', setItem() {} });
  invalid.getState().restoreMode();
  assert.equal(invalid.getState().mode, 'student');
  const blocked = store({ getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); } });
  blocked.getState().restoreMode();
  blocked.getState().setMode('senior');
  assert.equal(blocked.getState().mode, 'senior');
});
