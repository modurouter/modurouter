const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const ts = require('typescript');
function load(path, extras) {
  const target = {};
  runInNewContext(ts.transpileModule(readFileSync(path,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,
    {exports:target, Error, Date, JSON, TextDecoder, Headers, FormData, Response, AbortSignal, URL, crypto, setTimeout, ...extras});
  return target;
}
function setup(fetcher, settings={loaded:false}) {
  const calls=[];
  const fetch = async (url, init={}) => { calls.push({url,init}); return fetcher(url,init); };
  const api=load('src/lib/api.ts',{fetch});
  const state={messages:[],streaming:false,add(m){this.messages.push(m)},patch(id,p){Object.assign(this.messages.find(m=>m.id===id),p)},setStreaming(v){this.streaming=v}};
  const hook=load('src/lib/use-chat-api.ts',{fetch,require(name){if(name==='react')return {useRef:v=>({current:v}),useEffect:()=>{}};if(name==='./api')return api;if(name==='./model-settings')return {useModelSettings:{getState:()=>settings},effortOptions:[{id:'minimal'},{id:'low'}]};if(name==='./chat-store')return {useChatStore:{getState:()=>state}};throw Error(name);}}).useChatApi();
  return {calls,state,hook};
}
const result=(status='completed')=>({run_id:'run-1',status,response:'5입니다.',sources:[],selected_model:'test/model',providers:['test']});
function common(url) {
  if(url.endsWith('/v1/me'))return Response.json({id:'guest',csrf_token:'csrf-test'});
  if(url.endsWith('/v1/conversations'))return Response.json({id:'conversation-1'});
}
function stream(events) {return new Response(events.map(([kind,data])=>`event: ${kind}\ndata: ${JSON.stringify({run_id:'run-1',...data})}\n\n`).join(''),{headers:{'Content-Type':'text/event-stream'}})}
test('real-contract stream updates content, verifies saved result, and uses supported mode only',async()=>{
 const {hook,state,calls}=setup((url)=>common(url)|| (url.endsWith('/runs')?stream([['meta',{}],['status',{status:'model'}],['delta',{text:'5입니다.'}],['done',{status:'completed'}]]):Response.json(result())));
 await hook.send('2+3','child');
 assert.equal(state.streaming,false); assert.equal(state.messages[1].content,'5입니다.');assert.equal(state.messages[1].activity.status,'complete');
 const req=calls.find(c=>c.url.endsWith('/runs'));const body=JSON.parse(req.init.body); assert.equal(body.explanation_mode,'simple');assert.equal('model' in body,false);assert.equal('effort' in body,false);assert.equal(req.init.headers['X-CSRF-Token'],'csrf-test');assert.ok(req.init.headers['Idempotency-Key']);
});
test('admission failures remain errors, not fake completions',async()=>{
 const {hook,state}=setup(url=>common(url)||Response.json({code:'BUDGET_EXCEEDED',message:'오늘 한도 초과'},{status:429}));
 await hook.send('질문','student');assert.equal(state.messages[1].activity.status,'error');assert.equal(state.messages[1].error,'오늘 한도 초과');assert.equal(state.streaming,false);
});
test('ambiguous request retries reuse idempotency key and existing conversation',async()=>{
 let attempts=0;const {hook,calls}=setup(url=>{const r=common(url);if(r)return r;if(url.endsWith('/runs')){if(++attempts===1)throw Error('network');return Response.json(result());}return Response.json(result())});
 await hook.send('질문','student');await hook.send('질문','student');const requests=calls.filter(c=>c.url.endsWith('/runs'));assert.equal(requests[0].init.headers['Idempotency-Key'],requests[1].init.headers['Idempotency-Key']);assert.equal(calls.filter(c=>c.url.endsWith('/v1/conversations')).length,1);
});
test('truncated stream recovers stored run without another generation',async()=>{
 const {hook,state,calls}=setup(url=>common(url)||(url.endsWith('/runs')?stream([['meta',{}],['delta',{text:'5'}]]):Response.json(result())));
 await hook.send('질문','student');assert.equal(state.messages[1].content,'5입니다.');assert.equal(calls.filter(c=>c.url.endsWith('/runs')).length,1);
});
test('Stop calls cancellation endpoint and confirms cancelled state',async()=>{
 let controller;const response=new Response(new ReadableStream({start(c){controller=c;c.enqueue(new TextEncoder().encode('event: meta\ndata: {"run_id":"run-1"}\n\n'));}}),{headers:{'Content-Type':'text/event-stream'}});
 const {hook,state,calls}=setup(url=>{const r=common(url);if(r)return r;if(url.endsWith('/cancel')){controller.close();return Response.json(null)}if(url.endsWith('/runs'))return response;return Response.json(result('cancelled'));});
 const pending=hook.send('질문','student');await new Promise(r=>setTimeout(r,10));await hook.stop();await pending;
 assert.ok(calls.some(c=>c.url.endsWith('/cancel')));assert.equal(state.messages[1].activity.status,'stopped');assert.equal(state.streaming,false);
});
test('proxy rejects cross-origin writes and arbitrary paths before contacting upstream',async()=>{
 let count=0;const route=load('src/app/api/backend/[...path]/route.ts',{process:{env:{API_UPSTREAM_URL:'https://example.test',BACKEND_WEB_ORIGIN:'https://web.test'}},fetch:()=>{count++;throw Error('unexpected')},require:()=>({})});
 const request={method:'POST',headers:new Headers({origin:'https://evil.test'}),nextUrl:new URL('http://localhost:3107/api/backend/auth/guest')};
 assert.equal((await route.POST(request,{params:Promise.resolve({path:['auth','guest']})})).status,403);
 assert.equal((await route.POST(request,{params:Promise.resolve({path:['auth','admin']})})).status,404);assert.equal(count,0);
});
test('proxy preserves SSE, CSRF and session cookie without forwarding unrelated cookies',async()=>{
 let received;const route=load('src/app/api/backend/[...path]/route.ts',{process:{env:{API_UPSTREAM_URL:'https://example.test',BACKEND_WEB_ORIGIN:'https://web.test'}},fetch:async(url,init)=>{received=init;return stream([['done',{status:'completed'}]])},require:()=>({})});
 const request={method:'POST',headers:new Headers({origin:'http://localhost:3107','x-csrf-token':'csrf-test','idempotency-key':'key'}),cookies:{get:()=>({value:'session-test'})},nextUrl:new URL('http://localhost:3107/api/backend/v1/conversations/abc/runs'),signal:new AbortController().signal,text:async()=>'{"message":"hi"}',arrayBuffer:async()=>new TextEncoder().encode('{"message":"hi"}').buffer};
 const response=await route.POST(request,{params:Promise.resolve({path:['v1','conversations','abc','runs']})});assert.equal(response.status,200);assert.equal(received.headers.get('origin'),'https://web.test');assert.equal(received.headers.get('cookie'),'modurouter_session=session-test');assert.equal(received.headers.get('x-csrf-token'),'csrf-test');assert.match(await response.text(),/event: done/);
});

test('selected server model and low effort reach the run payload',async()=>{
 const {hook,calls}=setup(url=>common(url)||(url.endsWith('/runs')?Response.json(result()):Response.json(result())),{loaded:true,model:'test/model',effort:1,models:[{id:'test/model',efforts:['minimal','low']}]});
 await hook.send('질문','student');const body=JSON.parse(calls.find(c=>c.url.endsWith('/runs')).init.body);assert.equal(body.model,'test/model');assert.equal(body.reasoning_effort,'low');
});

for (const [name, origin, env, status] of [
 ['localhost with wildcard bind', 'http://localhost:3107', {NODE_ENV:'development'}, 200],
 ['loopback with wildcard bind', 'http://127.0.0.1:3107', {NODE_ENV:'development'}, 200],
 ['external origin', 'https://evil.test', {NODE_ENV:'development'}, 403],
 ['different port', 'http://localhost:9999', {NODE_ENV:'development'}, 403],
 ['missing origin', null, {NODE_ENV:'development'}, 403],
 ['opaque origin', 'null', {NODE_ENV:'development'}, 403],
 ['production rejects localhost', 'http://localhost:3107', {NODE_ENV:'production',FRONTEND_ORIGIN:'https://app.test'}, 403],
 ['configured production origin', 'https://app.test', {NODE_ENV:'production',FRONTEND_ORIGIN:'https://app.test'}, 200],
 ['forged forwarded host', 'https://evil.test', {NODE_ENV:'production',FRONTEND_ORIGIN:'https://app.test'}, 403],
]) {
 test(`proxy origin validation: ${name}`,async()=>{
  let calls=0;
  const route=load('src/app/api/backend/[...path]/route.ts',{process:{env:{API_UPSTREAM_URL:'https://backend.test',BACKEND_WEB_ORIGIN:'https://app.test',...env}},fetch:async()=>{calls++;return Response.json({ok:true})},require:()=>({})});
  const headers=new Headers({'host':'evil.test','x-forwarded-host':'evil.test'});
  if(origin!==null)headers.set('origin',origin);
  const request={method:'POST',headers,cookies:{get:()=>undefined},nextUrl:new URL('http://0.0.0.0:3107/api/backend/auth/guest'),signal:new AbortController().signal,text:async()=>''};
  const response=await route.POST(request,{params:Promise.resolve({path:['auth','guest']})});
  assert.equal(response.status,status);assert.equal(calls,status===200?1:0);
 });
}
