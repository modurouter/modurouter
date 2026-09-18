const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {runInNewContext} = require('node:vm');
const ts = require('typescript');

const exportsObject = {};
const source = readFileSync(resolve(__dirname, '../src/lib/api.ts'), 'utf8');
runInNewContext(ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS}}).outputText,
  {exports: exportsObject, TextDecoder, Headers, FormData, fetch, process});
const {consumeEvents, responseError} = exportsObject;

test('SSE preserves Unicode and CRLF framing across byte boundaries', async () => {
  const data = new TextEncoder().encode('event: delta\r\ndata: {"text":"한국어"}\r\n\r\nevent: done\r\ndata: {"status":"completed"}\r\n\r\n');
  const response = new Response(new ReadableStream({start(controller) {
    for (const byte of data) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  }}));
  const events = [];
  await consumeEvents(response, (kind, data) => events.push({kind, data}));
  assert.equal(events.length, 2);
  assert.equal(events[0].data.text, '한국어');
  assert.equal(events[1].kind, 'done');
});

test('proxy HTML failures produce an actionable error', async () => {
  const error = await responseError(new Response('<h1>Bad Gateway</h1>', {status: 502}));
  assert.equal(error.status, 502);
  assert.equal(error.code, 'NETWORK_ERROR');
  assert.match(error.message, /다시 시도/);
});

test('API failures preserve the server error message', async () => {
  const error = await responseError(Response.json({code: 'REQUEST_LIMIT', message: '오늘 한도 초과'}, {status: 429}));
  assert.equal(error.code, 'REQUEST_LIMIT');
  assert.equal(error.message, '오늘 한도 초과');
});


test('saved run errors retain an actionable reason after reload', () => {
  assert.match(exportsObject.runErrorMessage('SEARCH_UNAVAILABLE'), /웹 검색/);
  assert.match(exportsObject.runErrorMessage('PAGE_UNAVAILABLE'), /페이지/);
  assert.match(exportsObject.runErrorMessage('UNKNOWN'), /다시 시도/);
});
