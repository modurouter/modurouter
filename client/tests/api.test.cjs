const {test} = require('node:test');
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const {runInNewContext} = require('node:vm');
const ts = require('typescript');

const exportsObject = {};
const source = readFileSync(resolve(__dirname, '../src/lib/api.ts'), 'utf8');
runInNewContext(ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText,
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

for (const signedIn of [false, true]) {
  test(`session bootstrap ${signedIn ? 'keeps the signed-in account' : 'starts a guest without login'}`, async () => {
    const calls = [];
    const target = {};
    runInNewContext(ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText,
      {exports: target, TextDecoder, Headers, FormData, process, fetch: async (url, init) => {
        calls.push([url, init.method || 'GET']);
        if (calls.length === 1 && !signedIn) return Response.json({code: 'AUTH_REQUIRED'}, {status: 401});
        if (url.endsWith('/auth/guest')) return Response.json({started: true});
        return Response.json({id: signedIn ? 'member' : 'guest', guest: !signedIn});
      }});
    const user = await target.ensureSession();
    assert.equal(user.guest, !signedIn);
    assert.deepEqual(calls.map(([url, method]) => [new URL(url, 'http://test').pathname, method]),
      signedIn ? [['/v1/me', 'GET']] : [['/v1/me', 'GET'], ['/auth/guest', 'POST'], ['/v1/me', 'GET']]);
  });
}

test('session bootstrap does not replace an account on service failures', async () => {
  const target = {};
  let calls = 0;
  runInNewContext(ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText,
    {exports: target, TextDecoder, Headers, FormData, process, fetch: async () => {
      calls++;
      return Response.json({code: 'SERVICE_UNAVAILABLE'}, {status: 503});
    }});
  await assert.rejects(target.ensureSession(), {status: 503});
  assert.equal(calls, 1);
});

function withFetch(fetcher) {
  const target = {};
  runInNewContext(ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText,
    {exports: target, TextDecoder, Headers, FormData, process, fetch: fetcher});
  return target;
}

test('network failure is actionable for both JSON and streaming requests', async () => {
  const target = withFetch(async () => {throw new TypeError('Failed to fetch')});
  for (const request of [() => target.api('/v1/conversations'), () => target.fetchApi('/v1/conversations/one/runs')]) {
    await assert.rejects(request(), error => error.code === 'NETWORK_ERROR' && /인터넷 연결.*다시 전송/.test(error.message));
  }
});

test('intentional abort is preserved', async () => {
  const controller = new AbortController();
  controller.abort();
  const target = withFetch(async () => {throw controller.signal.reason});
  await assert.rejects(target.fetchApi('/v1/conversations', {signal: controller.signal}), {name: 'AbortError'});
});

test('draft attachment restoration refreshes statuses and keeps unavailable files visible', async () => {
  const target = withFetch(async url => {
    if (url.endsWith('missing')) return Response.json({}, {status: 404});
    if (url.endsWith('offline')) throw new TypeError('Failed to fetch');
    return Response.json({id: 'ready', filename: 'notice.txt', status: 'ready', preview: '파란 강의실'});
  });
  const saved = target.readSavedAttachments(JSON.stringify([
    {id: 'ready', filename: 'notice.txt'}, {id: 'missing', filename: 'old.txt'}, {id: 'offline', filename: 'pending.txt'}]));
  const restored = await target.restoreAttachments(saved);
  assert.deepEqual(Array.from(restored, a => a.status), ['ready', 'expired', 'unavailable']);
  assert.equal(restored[0].preview, '파란 강의실');
  assert.match(target.attachmentErrorMessage(restored[1]), /다시 첨부/);
  assert.match(target.attachmentErrorMessage(restored[2]), /대화를 다시 열거나/);
});

test('restoring draft files never hides authentication failures', async () => {
  const target = withFetch(async () => Response.json({code: 'AUTH_REQUIRED'}, {status: 401}));
  await assert.rejects(target.restoreAttachments([{id: 'file', filename: 'notice.txt'}]), {status: 401});
});

test('attachment failures explain recovery for every extractor error', () => {
  for (const code of ['PDF_ENCRYPTED', 'PDF_PAGE_LIMIT', 'NO_EXTRACTABLE_TEXT', 'FILE_ENCODING_INVALID',
    'IMAGE_PIXEL_LIMIT', 'OCR_LOW_CONFIDENCE', 'OCR_FAILED', 'OCR_TIMEOUT', 'EXTRACTION_TIMEOUT',
    'WORKER_INTERRUPTED', 'FILE_UNSUPPORTED', 'UPLOAD_FAILED', 'EXTRACTION_FAILED',
    'HWP_ENCRYPTED', 'HWP_PROTECTED', 'HWP_INVALID', 'HWP_VERSION_UNSUPPORTED', 'HWP_SIZE_LIMIT']) {
    assert.match(exportsObject.attachmentErrorMessage({status: 'failed', error_code: code}), /첨부/);
  }
  assert.match(exportsObject.attachmentErrorMessage({status: 'failed', error_code: 'PDF_ENCRYPTED'}), /암호를 해제/);
  assert.match(exportsObject.attachmentErrorMessage({status: 'failed', error_code: 'HWP_ENCRYPTED'}), /암호를 해제/);
  assert.match(exportsObject.attachmentErrorMessage({status: 'failed', error_code: 'HWP_VERSION_UNSUPPORTED'}), /HWPX/);
  assert.match(exportsObject.attachmentErrorMessage({status: 'failed', error_code: 'HWP_INVALID'}), /손상/);
  assert.match(exportsObject.runErrorMessage('ATTACHMENT_EXPIRED'), /원문.*다시 첨부/);
  assert.equal(exportsObject.attachmentErrorMessage({status: 'ready'}), null);
});
